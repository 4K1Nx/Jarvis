"""Headless HUD regression against synthetic local endpoints, never the live assistant."""
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
import json
import threading
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'artifacts' / 'viv-1.2'
OUT.mkdir(parents=True, exist_ok=True)
class Static(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass
    def translate_path(self, path):
        if path.startswith('/static/'):
            path = path[len('/static'):]
        return super().translate_path(path)

server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Static, directory=str(ROOT / 'web')))
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
fixture = {'mode':'live','state':'idle','stt':{'model':'small','device':'CPU / int8','ready':True},
           'gemini':{'model':'gemini-2.5-flash','status':'unverified'},
           'tts':{'engine':'edge','voice':'pt-BR-FranciscaNeural'},'input_device':2,'input_name':'Microfone (Realtek(R) Audio)','memory_turns':12,'sensitivity':'normal','research':None,
           'ram':{'process_ram_gb':2.1,'system_ram_used_gb':10.4,'system_ram_total_gb':32}, 'latency':None,'local_mode':True,'transcription_only':False,'gaps':'Cota Gemini indisponível'}
requests = []
errors = []
try:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel='msedge', headless=True)
        page = browser.new_page(viewport={'width':1440,'height':1100}, device_scale_factor=1)
        page.on('pageerror', lambda error: errors.append(str(error)))
        def api(route):
            path = route.request.url.split('/api/')[1]
            requests.append(path)
            if path.startswith('audio/transcription-test/'):
                fixture['transcription_only']=path.endswith('/on')
            data = fixture if path=='status' else {'records':[], 'ok':True}
            route.fulfill(json=data)
        page.route('**/api/**', api)
        sockets=[]
        page.route_web_socket('**/ws', lambda ws: sockets.append(ws))
        page.goto(f'http://127.0.0.1:{server.server_port}/', wait_until='networkidle')
        assert page.title().startswith('VIV 1.2')
        assert page.locator('.tips-panel').is_visible()
        assert 'Organize seu dia' in page.locator('.tips-panel').text_content()
        assert 'jarvis' not in page.locator('.tips-panel').text_content().lower()
        assert 'Realtek' in page.locator('#mic').inner_text()
        assert page.locator('.presence #status-alert').count()==1
        assert page.locator('#wakeBtn span').count()==0
        assert 'Ei, Viv' in page.locator('.activation').inner_text()
        assert page.locator('#gemini').inner_text().endswith('Conexão ainda não verificada')
        page.get_by_role('button', name='ATIVAR VIV').click()
        assert 'wake' in requests
        page.locator('#verify-gemini').click()
        page.wait_for_timeout(100)
        assert 'gemini/verify' in requests
        assert page.locator('.conversation-stack #assistant').count()==1
        assert page.locator('.flat-mark .facet-green').count()==1
        assert page.locator('#globe').count()==0
        assert page.locator('.flat-core').count()==1

        assert len(sockets)==1
        page.evaluate('connect(); connect();')
        assert len(sockets)==1
        ws=sockets[0]
        page.locator('#transcription-test').check()
        page.wait_for_function("document.getElementById('transcription-note').textContent.includes('somente')")
        assert 'audio/transcription-test/on' in requests
        ws.send(json.dumps({'channel':'reminder','text':'Beber água'}))
        page.wait_for_function("document.getElementById('last-reminder').textContent.includes('Beber água')")
        for state in ['sleeping','idle','listening','thinking','searching','speaking','error','unavailable']:
            fixture['state']=state
            ws.send(json.dumps({'channel':'state','text':state}))
            page.wait_for_function('(state)=>document.body.dataset.state===state', arg=state)
            page.screenshot(path=str(OUT / f'hud-{state}.png'), full_page=True)
        fixture['state']='thinking'
        ws.send(json.dumps({'channel':'state','text':'thinking'}))
        page.wait_for_function("document.body.dataset.state==='thinking'")
        assert page.locator('.flat-mark path').first.evaluate('(e)=>getComputedStyle(e).animationName')=='core-facet'
        fixture['state']='idle'
        ws.send(json.dumps({'channel':'state','text':'idle'}))
        ws.send(json.dumps({'channel':'outcome','status':'success'}))
        page.wait_for_function("document.body.dataset.outcome==='success'")
        assert 'audit' not in requests  # No per-event audit downloads.
        ws.send(json.dumps({'channel':'service','service':'gemini','status':'ok'}))
        page.wait_for_function("document.getElementById('gemini').textContent.includes('Conectado')")
        fixture['state']='listening'
        ws.send(json.dumps({'channel':'state','text':'listening'}))
        page.wait_for_function("document.body.dataset.state==='listening'")
        assert page.locator('.listening-wave i').first.evaluate('(e)=>getComputedStyle(e).animationName')=='core-wave'
        fixture['state']='confirm'
        ws.send(json.dumps({'channel':'state','text':'confirm'}))
        ws.send(json.dumps({'channel':'sys','pending':{'name':'TESTE SIMULADO','args':{}}}))
        page.locator('#approve').click()
        assert 'confirm/yes' in requests
        page.locator('#reject').click()
        assert 'confirm/no' in requests
        ws.send(json.dumps({'channel':'user','text':'<img src=x onerror=alert(1)>'}))
        page.wait_for_function("document.getElementById('user').textContent.includes('<img')")
        assert page.locator('#user img').count()==0
        page.locator('.audit summary').click()
        page.wait_for_function("document.getElementById('audit-count').textContent.includes('registros')")
        assert 'audit' in requests
        fixture['state']='idle'
        ws.send(json.dumps({'channel':'state','text':'idle'}))
        ws.send(json.dumps({'channel':'user','text':'Olá, Viv. Vamos conversar?'}))
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(OUT / 'hud-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#sensitivity').select_option('low')
        page.wait_for_function("document.getElementById('sensitivity-note').textContent.includes('aplicada')")
        assert 'audio/sensitivity/low' in requests
        ws.send(json.dumps({'channel':'research','status':'completed','sources':[{'title':'Fonte de teste','url':'https://example.org/research'},{'title':'unsafe','url':'javascript:alert(1)'}]}))
        page.wait_for_function("document.querySelectorAll('#sources a').length===1")
        assert page.locator('#sources a').get_attribute('href')=='https://example.org/research'
        ws.send(json.dumps({'channel':'level','value':0.2,'source':'microphone'}))
        page.wait_for_function("document.getElementById('mic-level').style.width==='20%'")
        ws.send(json.dumps({'channel':'level','value':0.9,'source':'playback'}))
        page.wait_for_timeout(50)
        assert page.locator('#mic-level').evaluate('(e)=>e.style.width')=='20%'
        page.set_viewport_size({'width':1440,'height':1100})
        for visual_state in ('thinking','error','listening'):
            page.evaluate('(s)=>setState(s)',visual_state)
            page.wait_for_timeout(350)
            assert 'core-emerald' in page.locator('.flat-mark .facet-green').evaluate('(e)=>getComputedStyle(e).fill')
            page.locator('.flat-core').screenshot(path=str(OUT / ('core-'+visual_state+'.png')))
        page.emulate_media(reduced_motion='reduce')
        assert page.locator('.orbit-primary').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
        assert page.locator('.flat-mark').evaluate('(e)=>getComputedStyle(e).animationName')=='none'
        page.locator('#model-picker summary').click()
        page.evaluate("showModels({status:'selected',selected:'gemini-3.1-flash-lite',rows:[{model:'gemini-3.1-flash-lite',input_price:.25,output_price:1.5,status:'ok',http_status:200}]})")
        assert 'gemini-3.1-flash-lite' in page.locator('#model-list').inner_text()
        page.locator('#select-model').click()
        page.wait_for_timeout(100)
        assert 'gemini/models/select' in requests
        page.route('**/api/status', lambda route:route.abort())
        page.evaluate("setState('thinking');snapshot()")
        page.wait_for_timeout(150)
        assert page.locator('body').get_attribute('data-state')=='unavailable'
        assert 'Servidor sem resposta' in page.locator('#conn').inner_text()
        assert not errors, errors
        browser.close()
    print('HUD PASS: 8 states, activation, confirmations, audit, Gemini status, safe text rendering, mobile layout; no JS errors.')
finally:
    server.shutdown()
    server.server_close()
