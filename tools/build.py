"""Merge extracted notes, verify quotes against the original text, and write the static site.
Usage: python3 tools/build.py <scratch_dir_with_book.json_and_outN.json>"""
import json,re,sys,glob,os
S=sys.argv[1]; R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
book=json.load(open(S+'/book.json'))
ids={s['id']:s for c in book for s in c['sections']}
ns=lambda x:re.sub(r'\s+','',x)
txt={k:ns(''.join(s['paras'])) for k,s in ids.items()}
alltxt=''.join(txt.values())
sections={};terms={};stories=[];bad=0;missing=[]
for f in sorted(glob.glob(S+'/out*.json')):
    d=json.load(open(f))
    for k,v in d.get('sections',{}).items():
        if k not in ids: continue
        q=[]
        for x in v.get('quotes') or []:
            if ns(x) in txt[k] or ns(x) in alltxt: q.append(x)
            else: bad+=1
        v['quotes']=q
        z=v.get('quiz')
        if z and not (isinstance(z.get('options'),list) and 2<=len(z['options'])<=4 and isinstance(z.get('answer'),int) and 0<=z['answer']<len(z['options'])): v['quiz']=None
        p=v.get('practice')
        if p and not p.get('steps'): v['practice']=None
        sections[k]=v
    for t in d.get('terms',[]):
        key=t['term'].strip()
        if key in terms:
            terms[key]['sections']+= [x for x in t.get('sections',[]) if x not in terms[key]['sections']]
            if len(t.get('def',''))>len(terms[key]['def']): terms[key]['def']=t['def']
        else: terms[key]={'term':key,'def':t.get('def',''),'sections':list(t.get('sections',[]))}
    stories+=d.get('stories',[])
missing=[k for k in ids if k not in sections]
extra=json.load(open(R+'/tools/extra.json')) if os.path.exists(R+'/tools/extra.json') else {}
notes={'sections':sections,'terms':sorted(terms.values(),key=lambda t:-len(t['sections'])),'stories':stories,
       'collections':extra.get('collections',{}),'start':extra.get('start',[]),
       'plan':json.load(open(R+'/tools/plan.json')) if os.path.exists(R+'/tools/plan.json') else None,
       'curriculum':json.load(open(R+'/tools/curriculum.json')) if os.path.exists(R+'/tools/curriculum.json') else None}
os.makedirs(R+'/site/data',exist_ok=True)
open(R+'/site/data/book.js','w').write('window.BOOK='+json.dumps(book,ensure_ascii=False,separators=(',',':'))+';\n')
open(R+'/site/data/notes.js','w').write('window.NOTES='+json.dumps(notes,ensure_ascii=False,separators=(',',':'))+';\n')
app=open(R+'/site/app.html').read()
open(R+'/site/index.html','w').write('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n<style>[hidden]{display:none!important}img{max-width:100%}</style>\n</head>\n<body>\n'+app+'\n</body>\n</html>\n')
print('sections',len(sections),'/',len(ids),'missing',missing,'dropped quotes',bad,'terms',len(terms),'stories',len(stories),
      'practices',sum(1 for v in sections.values() if v.get('practice')),'quizzes',sum(1 for v in sections.values() if v.get('quiz')))
