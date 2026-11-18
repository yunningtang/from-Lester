"""Build the standalone manifest tool: inject verified quotes, write index.html (+ PWA files) and artifact.html."""
import json,os
R=os.path.dirname(os.path.dirname(os.path.abspath(__file__)));D=R+'/manifest-tool'
body=open(D+'/app.html').read().replace('/*QUOTES*/[]',json.dumps(json.load(open(D+'/quotes.json')),ensure_ascii=False,separators=(',',':')))
open(D+'/artifact.html','w').write(body)
head='''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#f1f0ec">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="显化随身">
<link rel="manifest" href="manifest.json">
<link rel="icon" href="icon.svg" type="image/svg+xml">
<link rel="apple-touch-icon" href="icon.svg">
<style>[hidden]{display:none!important}</style>
</head>
<body>
'''
open(D+'/index.html','w').write(head+body+'\n</body>\n</html>\n')
json.dump({"name":"显化随身","short_name":"显化","start_url":"./","display":"standalone","background_color":"#f1f0ec","theme_color":"#2f6690",
  "icons":[{"src":"icon.svg","sizes":"any","type":"image/svg+xml","purpose":"any maskable"}]},open(D+'/manifest.json','w'),ensure_ascii=False,indent=1)
open(D+'/icon.svg','w').write('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512"><rect width="512" height="512" rx="112" fill="#1d2a36"/><defs><radialGradient id="g" cx=".36" cy=".3" r=".75"><stop offset="0" stop-color="#eaf3fc"/><stop offset=".45" stop-color="#7fa9d2"/><stop offset="1" stop-color="#24486a"/></radialGradient></defs><circle cx="256" cy="256" r="150" fill="url(#g)"/></svg>')
open(D+'/sw.js','w').write("""const C='manifest-v1';
self.addEventListener('install',e=>e.waitUntil(caches.open(C).then(c=>c.addAll(['./','index.html','manifest.json','icon.svg'])).then(()=>self.skipWaiting())));
self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));
self.addEventListener('fetch',e=>{if(e.request.method!=='GET')return;e.respondWith(fetch(e.request).then(r=>{const cp=r.clone();caches.open(C).then(c=>c.put(e.request,cp));return r}).catch(()=>caches.match(e.request)))});
""")
print('built',len(body))
