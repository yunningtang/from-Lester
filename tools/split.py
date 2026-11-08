import re,json,sys
S=sys.argv[1]
t=open(S+'/raw.txt').read(); pages=t.split('\f')
ents=json.load(open(S+'/toc.json'))
# page offsets
offs=[];o=0
for p in pages: offs.append(o); o+=len(p)+1
full='\f'.join(pages)
def norm(s): return re.sub(r'\s+','',s)
pos=[];miss=[]
for title,pg in ents:
    pi=pg+7; start=offs[pi]; end=offs[min(pi+2,len(offs)-1)]
    key=norm(title.replace('☆',''))
    found=None
    # scan lines in window
    i=start
    for line in full[start:end].split('\n'):
        nl=norm(line).replace('☆','')
        if nl and (nl==key or (len(key)>3 and nl.startswith(key[:min(len(key),12)]) and len(nl)<len(key)+6) or ('Limitations' in key and nl.endswith(key[-12:]) and len(nl)<len(key)+4)):
            found=i;break
        i+=len(line)+1
    if found is None: miss.append((title,pg)); found=start
    pos.append(found)
print('miss',miss)
# check monotonic
for k in range(1,len(pos)):
    if pos[k]<pos[k-1]: print('nonmono',ents[k])
secs=[]
coll=None
for k,(title,pg) in enumerate(ents):
    s=pos[k]; e=pos[k+1] if k+1<len(ents) else len(full)
    txt=full[s:e]
    if title.startswith('【'):
        coll={'title':title.strip('【】 ').strip(),'page':pg,'sections':[],'intro':''}
        secs.append(coll)
        # intro text = text after heading before next entry
        coll['intro']=txt
        continue
    coll['sections'].append({'title':title,'page':pg,'text':txt})
json.dump(secs,open(S+'/sections_raw.json','w'),ensure_ascii=False)
for c in secs:
    print(c['title'],c['page'],len(c['intro']),len(c['sections']),sum(len(x['text']) for x in c['sections']))
