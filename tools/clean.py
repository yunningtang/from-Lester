import re,json,sys
S=sys.argv[1]
d=json.load(open(S+'/sections_raw.json'))
END='。！？!?”」）)…：:；;~～】"'
def clean(txt,title=None):
    txt=txt.replace('\f','\n')
    lines=[l.rstrip() for l in txt.split('\n')]
    lines=[l for l in lines if not re.fullmatch(r'\s*-\s*\d+\s*-\s*',l)]
    # drop heading line
    if title:
        for i,l in enumerate(lines[:3]):
            if re.sub(r'\s','',l).replace('☆','')==re.sub(r'\s','',title).replace('☆','').strip('【】'): lines=lines[i+1:];break
    paras=[];buf=''
    for l in lines:
        s=l.strip()
        if not s:
            if buf: paras.append(buf); buf=''
            continue
        starts_new=re.match(r'^(莱斯特|学生|旁白|磁带旁白|主持人|海尔|拉里|鲍勃|帕特|问|答|[A-Za-z一-龥]{1,6}[：:])',s) and buf
        if starts_new and re.match(r'^[^，。]{1,8}[：:]',s):
            paras.append(buf); buf=s; continue
        if buf and buf[-1] in END and not buf.endswith('，'):
            paras.append(buf); buf=s
        else:
            # join; add space only between latin
            if buf and re.match(r'[A-Za-z0-9]',buf[-1]) and re.match(r'[A-Za-z0-9]',s[0]): buf+=' '+s
            else: buf+=s
    if buf: paras.append(buf)
    return [p for p in paras if p.strip()]
out=[];sid=0;total=0
for ci,c in enumerate(d):
    col={'id':f'c{ci+1}','title':c['title'],'page':c['page'],'sections':[]}
    intro=clean(c['intro'],c['title'])
    if sum(len(p) for p in intro)>200:
        col['sections'].append({'id':f'c{ci+1}s0','title':'开篇','page':c['page'],'paras':intro})
    for si,s in enumerate(c['sections']):
        col['sections'].append({'id':f'c{ci+1}s{si+1}','title':s['title'].replace('☆','').strip(),'page':s['page'],'paras':clean(s['text'],s['title'])})
    for s in col['sections']: total+=sum(len(p) for p in s['paras'])
    out.append(col)
json.dump(out,open(S+'/book.json','w'),ensure_ascii=False)
print(total, sum(len(c['sections']) for c in out))
# merge empty parents
for c in out:
    ns=[];prefix=None
    for s in c['sections']:
        if not s['paras']: prefix=s['title']; continue
        if prefix and (re.match(r'^\d-\d$',s['title']) or c['id']=='c2'): s['title']=prefix.replace('与莱斯特的谈话 ','')+' · '+s['title']
        ns.append(s)
    c['sections']=ns
json.dump(out,open(S+'/book.json','w'),ensure_ascii=False)
# chunks
chunks=[];cur=[];n=0
for c in out:
    for s in c['sections']:
        L=sum(len(p) for p in s['paras'])
        if n+L>66000 and cur: chunks.append(cur);cur=[];n=0
        cur.append((c,s));n+=L
chunks.append(cur)
for i,ch in enumerate(chunks):
    with open(f'{S}/chunk{i+1}.txt','w') as f:
        for c,s in ch:
            f.write(f"\n\n===== SECTION {s['id']} | 合集《{c['title']}》 | {s['title']} | 原书第{s['page']}页 =====\n")
            f.write('\n'.join(s['paras']))
    print(i+1,len(ch),sum(sum(len(p) for p in s['paras']) for c,s in ch), ch[0][1]['id'], ch[-1][1]['id'])
