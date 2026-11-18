"""Verified Lester quotes on manifesting, for the standalone manifest tool."""
import json,re,sys,os
S=sys.argv[1];R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
book=json.load(open(S+'/book.json'));ns=lambda x:re.sub(r'\s+','',x)
sec={s['id']:(c['title'],s['title'],s['page'],ns(''.join(s['paras']))) for c in book for s in c['sections']}
Q=[('c6s6','现在，如果你无法拥有绝对的信念，你要做的就是在心智中坚持你想要的，然后带着它已经完成了的感觉放手。','hold'),
('c6s6','因为“它已经完成了”的态度是对其已经实现的这一事实的接纳。','done'),
('c6s6','我们必须把我们想要的东西放到现在，我们必须采取它现在就在这里的态度，然后放下它。','now'),
('c6s6','因为当我们在心理上把事物放在未来时，它就会永远停留在未来。','now'),
('c6s6','你想要的任何事物，你必须接受它已经是你的，否则它就一直在你前面、离你一步之遥。','done'),
('c6s6','现在阻碍我们得到我们想要的东西的，是相反的潜意识念头。','opp'),
('c6s6','所以如果你有意识地开始进行显化，如果你成功过一次，你就会更加坚信自己可以做到，如果你成功了两次，信念变得越来越强，直到有一天你拥有了绝对信念。','faith'),
('c6s6','事情显化的速度取决于你是否会得到它的信念，信念也是一个想法。','faith'),
('c6s7','我想象着那辆凯迪拉克，我看到我坐在里面，我能感觉到车里的感觉，当我驾驶它时，它是我的，我释放它，好像它已经实现了。','see'),
('c6s7','“觉得它已经实现了”是显化过程中很重要的一环。','done'),
('c6s7','先从小事做起，敢于显化一件非常小的事情并不难，当它起作用时，这会给你更多关于显化的信心，尝试第二次、第三次……信心就会建立起来。','small'),
('c6s7','显化并不在无限中，那是在梦境中。','note'),
('c2s0','当你变得无欲的时候，你能拥有任何一件你想要的事情，仅仅是通过一个念头。','want'),
('c4s2','仅仅只是把你的想法放到我们安静的心智里，它就会显化，即便不是马上显化，也会很快。','see'),
('c1s1','从现在开始，任何你想要的东西，都通过释放来得到它。','want'),
('c2s2','要发现幸福在哪里，它不在事物之中，它在于放下“没有它”的痛苦。','want'),
('c1s6','你有任何时候毫不费力地得到事物吗？完全没有努力，仅仅是掉到你膝盖上。','faith'),
('c2s1','在心理层面改变画面，外面会立即发生改变，这被称作“奇迹”。','see')]
out=[];bad=[]
for sid,q,tag in Q:
    if ns(q) in sec[sid][3]: out.append({'q':q,'c':sec[sid][0],'t':sec[sid][1],'p':sec[sid][2],'tag':tag})
    else: bad.append(q)
json.dump(out,open(R+'/manifest-tool/quotes.json','w'),ensure_ascii=False,indent=0)
print(len(out),'verified; not verbatim:',bad)
