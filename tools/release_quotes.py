"""Collect verified Lester quotes about releasing for the standalone release tool."""
import json,re,sys,os
S=sys.argv[1]; R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
book=json.load(open(S+'/book.json'))
ns=lambda x:re.sub(r'\s+','',x)
sec={s['id']:(c['title'],s['title'],s['page'],ns(''.join(s['paras']))) for c in book for s in c['sections']}
cur=[('c1s4','最基本的就是持续释放。'),
('c2s0','你们有没有特别注意去持续释放欲望，放走更多、放走更多、放走更多，直到没有更多？'),
('c7s26','你会审视每一个出现的感受，看到它是想要被认同、想要控制、还是想要安全，然后让它离开。'),
('c1s1','所以当你去做，这是非常轻松容易的，它们就像波浪一样浮现并离开，直到波浪停止，你也就完成了。'),
('c1s1','从现在开始，任何你想要的东西，都通过释放来得到它。'),
('c4s14','一开始可能是一天抽出一小时，然后是早上的一个小时和晚上的一个小时，接着是几个小时，然后是半天，最后你会花上一整天时间。'),
('c4s1','让心智完全安静下来，就是这么简单。'),
('c1s6','当它开始浮现，请让它离开。'),
('c1s7','你现在就是完全自由的，你是全能的，你是全知的，你是全在的。'),
('c5s4','如果你觉得累了，就释放“想要改变疲惫”，你就会恢复精力。'),
('c1s1','释放“想要改变这个模糊不清的感受”'),
('c1s1','当你释放了那些，在它们底端的“对死亡的恐惧”，就会自然地、明显可察觉地浮现出来，给你去释放。'),
('c1s7','你设置了一个缺乏、想要、欲望去搅动你的心智，当你填补了这个欲望，心智变得安静起来，从而你仅仅是存在时，这就是你所感觉到的快乐')]
out=[];bad=[]
for sid,q in cur:
    if ns(q) in sec[sid][3]: out.append({'q':q,'c':sec[sid][0],'t':sec[sid][1],'p':sec[sid][2]})
    else: bad.append(q)
n=open(R+'/site/data/notes.js').read();n=json.loads(n[len('window.NOTES='):].rstrip().rstrip(';'))
kw=('释放','放下','想要','让它','感受','心智安静')
for sid,v in n['sections'].items():
    for q in v.get('quotes',[]):
        if any(k in q for k in kw) and 14<=len(q)<=60 and ns(q) in sec[sid][3] and not any(ns(q)==ns(o['q']) for o in out):
            out.append({'q':q,'c':sec[sid][0],'t':sec[sid][1],'p':sec[sid][2]})
json.dump(out,open(R+'/release-tool/quotes.json','w'),ensure_ascii=False,indent=0)
print(len(out),'quotes; not verbatim:',bad)
