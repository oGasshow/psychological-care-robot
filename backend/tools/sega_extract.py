"""Build an experimental SEGA tensor bundle from three aligned voice turns."""
import argparse
import json
from pathlib import Path

import numpy as np


EMOTIONS = ('anger', 'disgust', 'fear', 'joy', 'neutral', 'sadness', 'surprise')
RATE = 16000


def fixed_rows(matrix, length, width):
    matrix = np.asarray(matrix, dtype=np.float32)
    if matrix.ndim != 2 or matrix.shape[1] != width or not matrix.shape[0] or not np.isfinite(matrix).all():
        raise ValueError('invalid_feature_matrix')
    result = np.zeros((length, width), dtype=np.float32)
    rows = min(length, matrix.shape[0])
    result[:rows] = matrix[:rows]
    return result


def extract(config, source, pcm, destination):
    import opensmile
    import torch
    from transformers import AutoModel, AutoModelForSequenceClassification, AutoModelForSeq2SeqLM, AutoTokenizer

    def load(name, factory):
        local = Path(config[name]).resolve(strict=True)
        if not local.is_dir():
            raise ValueError('local_models_required')
        tokenizer = AutoTokenizer.from_pretrained(local, local_files_only=True)
        model = factory.from_pretrained(local, local_files_only=True, use_safetensors=True).eval()
        return tokenizer, model

    window_ms, hop_ms = (config[key] for key in ('audio_window_ms', 'audio_hop_ms'))
    if not 250 <= window_ms <= 5000 or not 20 <= hop_ms <= window_ms:
        raise ValueError('invalid_audio_window')
    window, hop = window_ms * RATE // 1000, hop_ms * RATE // 1000
    answers = load('answer_encoder', AutoModel)
    questions = answers if config['question_encoder'] == config['answer_encoder'] else load('question_encoder', AutoModel)
    translator, translation_model = load('zh_en_translation', AutoModelForSeq2SeqLM)
    classifier, emotion_model = load('emotion_classifier', AutoModelForSequenceClassification)
    label_ids = {str(name).lower(): int(index) for index, name in emotion_model.config.id2label.items()}
    if set(label_ids) != set(EMOTIONS):
        raise ValueError('unexpected_emotion_labels')
    smile = opensmile.Smile(feature_set=opensmile.FeatureSet.eGeMAPSv02, feature_level=opensmile.FeatureLevel.Functionals)
    torch.set_num_threads(2)

    def embed(text, encoder, length):
        tokenizer, model = encoder
        tokens = tokenizer(text, truncation=True, max_length=length, return_tensors='pt')
        hidden = model(**tokens).last_hidden_state[0].cpu().numpy()
        return fixed_rows(hidden, length, 768)

    if len(source['pairs']) != 3 or source['gender'] not in ('female', 'male'):
        raise ValueError('incomplete_source')
    text, question, audio, emotion = [], [], [], []
    with torch.inference_mode():
        for pair in source['pairs']:
            start, size = pair['offset'], pair['size']
            if start < 0 or size < 9600 or size % 2 or start + size > len(pcm):
                raise ValueError('invalid_aligned_audio')
            samples = np.frombuffer(pcm[start:start + size], dtype='<i2').astype(np.float32) / 32768
            offsets = range(0, max(1, samples.size - window + 1), hop)
            rows = [smile.process_signal(samples[offset:offset + window], RATE).to_numpy()[0]
                    for offset in list(offsets)[:112]]
            audio.append(fixed_rows(rows, 112, 88))
            text.append(embed(pair['answer'], answers, 128))
            question.append(embed(pair['question'], questions, 20))
            translated = translation_model.generate(**translator(pair['answer'], truncation=True, max_length=512,
                                                    return_tensors='pt'), max_new_tokens=128)
            english = translator.decode(translated[0], skip_special_tokens=True).strip()
            if not english:
                raise ValueError('empty_translation')
            logits = emotion_model(**classifier(english, truncation=True, max_length=512, return_tensors='pt')).logits[0]
            emotion.append(logits.softmax(dim=-1)[[label_ids[name] for name in EMOTIONS]].cpu().numpy())
    np.savez(destination, text=[text], question=[question], audio=[audio], emotion=[emotion],
             gender=[int(source['gender'] == 'male')],
             record_ids=[pair['answer_id'] for pair in source['pairs']],
             question_record_ids=[pair['question_id'] for pair in source['pairs']])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('config', 'source', 'audio', 'destination'):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        extract(json.loads(args.config.read_text(encoding='utf-8-sig')),
                json.loads(args.source.read_text(encoding='utf-8')), args.audio.read_bytes(), args.destination)
    except Exception as exc:
        raise SystemExit(type(exc).__name__) from None
