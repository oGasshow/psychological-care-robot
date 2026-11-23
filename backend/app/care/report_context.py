"""Conservative first-person excerpt selection, never a diagnostic classifier."""
import re

QUOTES=re.compile(r'“[^”]*”|‘[^’]*’|"[^"\n]*"|\x27[^\x27\n]*\x27|「[^」]*」|『[^』]*』')
THIRD=re.compile(r'^(?:(?:今天|昨天|最近|刚才|前天|这几天|那天|之前|听说|据说)\s*)*'
    r'(?:我(?:的)?(?:妈妈|爸爸|妈|爸|母亲|父亲|朋友|同事|孩子|儿子|女儿|家人)|'
    r'他|她|他们|她们|朋友|同事|家人|妈妈|爸爸|医生说|新闻|故事|电影|网上)')
HYPOTHETICAL=re.compile(r'如果|假如|假设|举个例子|你觉得|你会|是什么意思|你能|比如有人|测试一下')


def own_clauses(messages,excluded_ids=()):
    for message in messages:
        if message['record_id'] in excluded_ids:continue
        own=True
        for clause in re.split(r'[，,。！？!?；;\n]+',QUOTES.sub('',message['effective_content'])):
            clause=clause.strip()
            probe=re.sub(r'^(?:但是|可是|然而|不过|但|而|所以|然后)\s*','',clause)
            if not probe:continue
            if THIRD.search(probe) or HYPOTHETICAL.search(probe):own=False;continue
            if re.match(r'^(?:(?:现在|最近|今天|昨天|以前|这几天|其实)\s*)*(?:我|本人)',probe):own=True
            if not own:continue
            yield message,clause
