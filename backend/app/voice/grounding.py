"""Match source spans allowing typography differences, never paraphrases."""
import unicodedata


def source_span(quote, text):
    if not quote:return None
    if quote in text:return quote
    def keep(char):return not (char.isspace() or unicodedata.category(char).startswith('P'))
    positions=[i for i,char in enumerate(text) if keep(char)]
    needle=''.join(char for char in quote if keep(char))
    haystack=''.join(text[i] for i in positions)
    if len(needle)<2:return None
    start=haystack.find(needle)
    if start<0:return None
    return text[positions[start]:positions[start+len(needle)-1]+1]
