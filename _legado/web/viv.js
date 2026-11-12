'use strict';
const $ = id => document.getElementById(id);
const states = {sleeping:'Dormindo',idle:'Em espera',listening:'Ouvindo',thinking:'Processando',searching:'Pesquisando',speaking:'Falando',error:'Erro',unavailable:'Sem conexão / ferramenta indisponível',confirm:'Aguardando confirmação'};
const descriptions={sleeping:'Diga “Ei, Viv”, bata duas palmas ou toque em ATIVAR VIV.',idle:'Pronta para continuar a conversa.',listening:'Estou ouvindo. Ruídos breves são filtrados.',thinking:'Interpretando sua fala e preparando a resposta.',searching:'Consultando fontes e verificando a relevância.',speaking:'Pode interromper por voz ou pelo bot?o ATIVAR VIV.',error:'Não foi possível concluir. Você pode ativar a Viv e tentar novamente.',unavailable:'Verifique a conexão ou tente novamente mais tarde.',confirm:'A ação só será executada após sua confirmação.'};
const labels = {wake_whisper_ms:'Whisper · chamada Viv',capture_ms:'Captura / VAD',speaker_ms:'Verificação de voz',whisper_ms:'Whisper · transcrição',gemini_ms:'Gemini · resposta',tools_ms:'Ferramentas',search_ms:'Busca na internet',tts_generate_ms:'Edge TTS · geração',tts_decode_ms:'Decodificação',tts_playback_ms:'Reprodução',playback_start_ms:'Ativação → início do áudio'};
const channels = {wake:'Ativação recebida',stt:'Transcrição processada',llm:'Processamento da conversa',tool:'Ferramenta consultada',tts:'Resposta por voz',mem:'Memória atualizada',sys:'Evento do sistema',voice:'Verificação de voz',skill:'Comando rápido',proactive:'Rotina',rag:'Documentos',learn:'Aprendizado',browser:'Navegador',vision:'Visão',perf:'Diagnóstico atualizado'};
const auditLabels = {user_turn:'Entrada de voz',tool_requested:'Ferramenta solicitada',tool_executed:'Ferramenta executada',tool_blocked:'Ferramenta bloqueada',confirmation_requested:'Confirmação solicitada',confirmation_result:'Decisão registrada',confirmation_rejected:'Confirmação recusada',turn_error:'Falha na conversa'};
let state = 'idle', countdownTimer, socket, reconnectTimer, snapshotBusy = false, auditBusy = false;
let latestTurn = null, outcomeTimer, socketTimer;
for(const [key,label] of Object.entries(labels)){
  const row=document.createElement('div');row.className='timing';
  const name=document.createElement('span');name.textContent=label;
  const value=document.createElement('b');value.id=key;value.textContent='—';row.append(name,value);$('timings').append(row);
}
const format = ms => typeof ms === 'number' && Number.isFinite(ms) ? (ms/1000).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})+' s' : '—';
function setState(next){
  if(!states[next]) return;
  if(['listening','thinking','searching','error'].includes(next)){delete document.body.dataset.outcome;clearTimeout(outcomeTimer);}
  const changed=state!==next;if(changed)document.querySelector('.flat-core').style.setProperty('--core-level',0);state=next;document.body.dataset.state=next;$('state').textContent=states[next];$('status-title').textContent=states[next];$('status-detail').textContent=descriptions[next];
  $('confirm').hidden=next!=='confirm';
  if(next==='confirm' && changed) startCountdown();
  if(next!=='confirm') clearInterval(countdownTimer);
}
function line(text){
  const row=document.createElement('div'), stamp=document.createElement('time');stamp.textContent=new Date().toLocaleTimeString('pt-BR');
  row.append(stamp,document.createTextNode(text));$('log').append(row);
  while($('log').children.length>100) $('log').firstChild.remove();
  $('log').scrollTop=$('log').scrollHeight;
}
function timing(data){
  if(!data) return;
  latestTurn=data;
  for(const key of Object.keys(labels)) $(key).textContent=format(data[key]);
  $('response-time').textContent=format(data.response_start_ms);$('total-time').textContent=format(data.total_ms);
  const status={ok:'Concluído',empty:'Sem fala reconhecida',error:'Falha em uma etapa',wake_ignored:'Fala sem chamada Viv · descartada localmente'};
  $('timing-status').textContent=`${status[data.status]||'Aguardando'} · ${new Date(data.ts*1000).toLocaleTimeString('pt-BR')} · ${data.gemini_calls||0} chamada(s) Gemini`;
}
function ram(data){
  if(!data) return;
  const gb=n=>Number(n).toLocaleString('pt-BR',{maximumFractionDigits:1});
  $('ram-process').textContent=gb(data.process_ram_gb)+' GB';
  $('ram-system').textContent=gb(data.system_ram_used_gb)+' / '+gb(data.system_ram_total_gb)+' GB';
  $('ram-bar').style.width=Math.min(100,data.system_ram_used_gb/data.system_ram_total_gb*100)+'%';
}
function gemini(status,model=null,code=null,diagnostic=null){
  model=model||$('gemini').dataset.model||'Gemini';$('gemini').dataset.model=model;
  const errors={quota:'Cota ou limite de solicitações atingido',authentication:'Autenticação recusada',permission:'Acesso recusado',model_not_found:'Modelo indispon\u00edvel nesta chamada (HTTP 404)',generation_unsupported:'Modelo sem suporte a respostas de texto',invalid_response:'Resposta de verifica\u00e7\u00e3o inv\u00e1lida',invalid_request:'Requisição de conversa/ferramentas inválida',timeout:'Tempo de resposta esgotado',connection:'Falha de conexão',server_error:'Serviço temporariamente indisponível',empty_response:'Resposta vazia ou bloqueada',malformed_function_call:'Gemini retornou uma chamada de ferramenta inválida'};
  const text={retrying:'Servi\u00e7o ocupado \u00b7 tentando novamente',ok:'Conectado · última chamada OK',available:'Acesso ao modelo verificado · geração pendente',checking:'Verificando acesso…',error:'Falha de acesso ou chamada',unverified:'Conexão ainda não verificada'};
  $('gemini').textContent=model+' · '+(status==='error'&&errors[code]?errors[code]:(text[status]||text.unverified));
  if(status==='error' && diagnostic){
    const phase=diagnostic.phase==='generation'?'geração da resposta':'consulta do modelo';
    $('gemini').textContent+=' ? Falha na '+phase;
    const catalog=diagnostic.catalog;
    if(catalog?.status==='ok'){
      $('gemini').textContent+=catalog.configured_model_listed?' ? Modelo presente no catálogo, mas a chamada falhou.':' ? Modelo ausente do catálogo consultado.';
      const names=catalog.models.filter(n=>n.includes('flash')&&!/image|audio|live|tts|robotics/.test(n));
      if(names.length)$('gemini').textContent+=' Alternativas listadas (ainda não testadas): '+names.slice(0,8).join(', ');
    }
  }
  $('gemini-dot').classList.toggle('unknown',!['ok','available'].includes(status));
}
async function snapshot(){
  if(snapshotBusy||document.hidden) return;snapshotBusy=true;
  try{
    const response=await fetch('/api/status',{signal:AbortSignal.timeout(6000)});if(!response.ok) throw Error();const data=await response.json();
    $('mode').textContent=data.mode==='live'?(data.local_mode?'Comandos locais · sem geração Gemini':'Sessão de voz ativa'):'Demonstração visual · sem microfone';
    $('wakeBtn').disabled=data.mode!=='live';
    $('stt').textContent=`Whisper ${data.stt.model} · ${data.stt.device}${data.stt.ready?' · pronto':' · não carregado'}`;
    gemini(data.gemini.status,data.gemini.model,data.gemini.error_code,data.gemini.diagnostic);
    $('tts').textContent=`Edge TTS · ${data.tts.voice}`;
    $('gap-summary').textContent=data.gaps||'Nenhuma pendência registrada até agora.';
    $('transcription-test').checked=Boolean(data.transcription_only);
    $('sensitivity').value=data.sensitivity||'normal';if(data.research)researchStatus(data.research);
    $('mic').textContent=data.input_name||(data.input_device==null?'Nenhum microfone selecionado':('Dispositivo '+data.input_device));$('memory').textContent=data.memory_turns+' turnos';
    if(data.pending)$('pending').textContent=JSON.stringify(data.pending,null,2);
    if(data.mode==='live') setState(socket?.readyState===WebSocket.OPEN?data.state:'unavailable');audioHealth(data.audio_health);
    refreshModels();
    ram(data.ram);if(data.latency && data.latency.turn_id!==latestTurn?.turn_id) timing(data.latency);
  }catch(e){setState('unavailable');$('conn').textContent='Servidor sem resposta';$('mode').textContent='Sem conex\u00e3o com a Viv';$('status-detail').textContent='A HUD perdeu contato com o servidor. Confira o terminal da Viv.';}finally{snapshotBusy=false;}
}
function startCountdown(){clearInterval(countdownTimer);let left=25;$('countdown').textContent=left;countdownTimer=setInterval(()=>{$('countdown').textContent=--left;if(left<=0){clearInterval(countdownTimer);decide('no');}},1000);}
async function decide(choice){
  clearInterval(countdownTimer);
  try{const r=await fetch('/api/confirm/'+choice,{method:'POST'});if(!r.ok)throw Error();line(choice==='yes'?'Confirmação enviada':'Recusa enviada');}catch(e){line('Não foi possível enviar a decisão');}
}
$('approve').onclick=()=>decide('yes');$('reject').onclick=()=>decide('no');
$('wakeBtn').onclick=async()=>{
  const button=$('wakeBtn');button.disabled=true;
  let status=0;
  try{const r=await fetch('/api/wake',{method:'POST'});status=r.status;const d=await r.json();if(!r.ok||!d.ok)throw Error();line('Ativação solicitada');}
  catch(e){setState('unavailable');const message=status===409?'O ciclo de voz ainda está encerrando. Tente novamente em instantes.':status===503?'Servidor recusou a ativação (HTTP 503). Reinicie a Viv para carregar a versão corrigida.':status?'Falha na ativação (HTTP '+status+'). Confira o terminal da Viv.':'Servidor Viv sem resposta. Confira se o run.bat continua em execução.';line(message);$('status-detail').textContent=message;}
  finally{button.disabled=false;}
};
async function refreshAudit(){
  if(auditBusy||document.hidden||!document.querySelector('.audit').open)return;auditBusy=true;
  try{const r=await fetch('/api/audit');if(!r.ok)throw Error();const d=await r.json();const records=d.records||[];$('audit-count').textContent=records.length+' registros';$('audit-list').replaceChildren();
    for(const x of records.slice(-40).reverse()){const row=document.createElement('div');row.textContent=new Date(x.ts*1000).toLocaleTimeString('pt-BR')+' · '+(auditLabels[x.event]||'Evento registrado')+(x.tool?' · '+x.tool:'');$('audit-list').append(row);}
    if(!records.length)$('audit-list').textContent='Nenhum registro disponível.';
  }catch(e){$('audit-list').textContent='Auditoria indisponível.';}finally{auditBusy=false;}
}
document.querySelector('.audit').addEventListener('toggle',refreshAudit);
$('audit-export').onclick=()=>{location.href='/api/audit/export';};
function receive(m){
  if(m.channel==='outcome'){document.body.dataset.outcome=m.status;clearTimeout(outcomeTimer);outcomeTimer=setTimeout(()=>{delete document.body.dataset.outcome;},2500);return;}
  if(m.channel==='reminder'){$('last-reminder').textContent='Lembrete: '+m.text;line('Lembrete recebido');return;}
  if(m.channel==='level'){const v=Math.max(0,Math.min(1,Number(m.value)||0));if((state==='listening'&&m.source==='microphone')||(state==='speaking'&&m.source==='playback'))document.querySelector('.flat-core').style.setProperty('--core-level',v);document.body.style.setProperty('--level',v);if(m.source!=='playback')$('mic-level').style.width=(v*100)+'%';return;}
  if(m.channel==='research'){researchStatus(m);return;}
  if(m.channel==='state'){setState(m.text);return;}
  if(m.channel==='res'){ram(m);return;}
  if(m.channel==='service'){if(m.service==='gemini')gemini(m.status,m.model,m.error_code);return;}
  if(m.channel==='stage'){if(labels[m.stage])$(m.stage).textContent=format(m.duration_ms);return;}
  if(m.channel==='perf'){timing(m);return;}
  if(m.channel==='user')$('user').textContent=m.text;
  if(m.channel==='tts'&&m.text.startsWith('Viv: '))$('assistant').textContent=m.text.slice(5);
  if(m.channel==='skill')$('v-skill').textContent='Comandos: executado';
  if(m.channel==='rag')$('v-rag').textContent='Documentos: atividade';
  if(m.channel==='voice'||m.channel==='spk')$('v-spk').textContent='Voz: verificação realizada';
  if(m.channel==='proactive')$('v-pro').textContent='Rotinas: atividade';
  if(m.channel==='learn')$('v-learn').textContent='Aprendizado: atividade';
  if(m.pending)$('pending').textContent=JSON.stringify(m.pending,null,2);
  if(channels[m.channel])line(channels[m.channel]);
}
const researchLabels={started:'Pesquisa iniciada',received:'Resultados recebidos',relevant:'Resultados relevantes encontrados',completed:'Pesquisa concluída',no_relevant_results:'Pesquisa sem resultados relevantes',tool_error:'Erro na ferramenta'};
function researchStatus(data){
  $('research-status').textContent=(researchLabels[data.status]||'Pesquisa')+(typeof data.count==='number'?' · '+data.count:'');
  if(data.status==='started')$('sources').replaceChildren();
  if(Array.isArray(data.sources)){
    $('sources').replaceChildren();
    for(const source of data.sources){
      try{const url=new URL(source.url);if(!['http:','https:'].includes(url.protocol)||url.username||url.password)continue;
        const a=document.createElement('a');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';a.textContent=source.title||url.hostname;$('sources').append(a);
      }catch(e){}
    }
  }
}
$('sensitivity').onchange=async()=>{
  try{const r=await fetch('/api/audio/sensitivity/'+$('sensitivity').value,{method:'POST'});if(!r.ok)throw Error();$('sensitivity-note').textContent='Sensibilidade aplicada nesta sessão.';}catch(e){$('sensitivity-note').textContent='Não foi possível aplicar a sensibilidade.';}
};
function connect(){
  if(socket && [WebSocket.OPEN,WebSocket.CONNECTING].includes(socket.readyState))return;
  clearTimeout(reconnectTimer);
  socket=new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws`);
  clearTimeout(socketTimer);const current=socket;socketTimer=setTimeout(()=>{if(current.readyState===WebSocket.CONNECTING)current.close();},8000);
  socket.onopen=()=>{clearTimeout(socketTimer);$('conn').textContent='● HUD conectada';snapshot();};
  socket.onclose=()=>{clearTimeout(socketTimer);setState('unavailable');$('conn').textContent='○ HUD desconectada';clearTimeout(reconnectTimer);reconnectTimer=setTimeout(connect,3000);};
  socket.onerror=()=>{$('conn').textContent='Falha na conexão da HUD';};
  socket.onmessage=e=>{try{receive(JSON.parse(e.data));}catch(err){line('Evento inválido recebido');}};
}
connect();snapshot();setInterval(snapshot,5000);setInterval(refreshAudit,10000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)snapshot();});

function audioHealth(data){
  if(!data)return;
  const failed=['error','no_frames'].includes(data.status)||data.frame_age_s>3;
  const c=data.capture||{};
  $('audio-health').textContent=failed?'Captura da Viv interrompida. Clique ATIVAR VIV para tentar recuperar.':
    data.frame_age_s==null?'Aguardando os primeiros quadros do microfone.':
    'Microfone recebendo áudio'+(typeof c.peak_rms==='number'?` · pico ${(20*Math.log10(Math.max(c.peak_rms,0.000001))).toFixed(0)} dBFS · ${c.speech_frames} quadros de fala`:'.')+(c.quality?' · '+c.quality:'');
  if(failed){setState('error');$('status-detail').textContent=$('audio-health').textContent;}
}
$('verify-gemini').onclick=async()=>{
  $('verify-gemini').disabled=true;gemini('checking');
  try{const r=await fetch('/api/gemini/verify',{method:'POST'});if(!r.ok)throw Error();const result=await r.json();gemini(result.status,result.model,result.error_code,result.diagnostic);}
  catch(e){gemini('error');}finally{$('verify-gemini').disabled=false;}
};

$('transcription-test').onchange=async()=>{
  const enabled=$('transcription-test').checked;
  try{const r=await fetch('/api/audio/transcription-test/'+(enabled?'on':'off'),{method:'POST'});if(!r.ok)throw Error();$('transcription-note').textContent=enabled?'Próximo turno: somente transcrição. Clique ATIVAR VIV e fale.':'Modo de conversa restaurado para o próximo turno.';}
  catch(e){$('transcription-test').checked=!enabled;$('transcription-note').textContent='Não foi possível mudar o modo.';}
};

let modelsBusy=false;
function showModels(data){
  const names={pending:'Não testado',not_listed:'Ausente no catálogo',testing:'Testando',ok:'Respondeu',failed:'Falhou',empty:'Sem resposta',timeout_or_connection:'Tempo esgotado / conexão'};
  $('model-list').replaceChildren();
  for(const row of data.rows||[]){const item=document.createElement('li');item.textContent=row.model+' ? $'+row.input_price+' / $'+row.output_price+' ? '+(names[row.status]||row.status)+(row.http_status?' ? HTTP '+row.http_status:'');$('model-list').append(item);}
  $('select-model').disabled=data.status==='testing';
  $('model-selection-state').textContent=data.selected?'Selecionado para a próxima conversa nesta sessão: '+data.selected:data.status==='testing'?'Testando em ordem de custo. Um teste curto por modelo.':data.status==='idle'?'Aguardando teste.':'Nenhum modelo selecionado. Confira os resultados; o modelo anterior foi preservado.';
}
async function refreshModels(){
  if(modelsBusy)return;modelsBusy=true;
  try{const r=await fetch('/api/gemini/models',{signal:AbortSignal.timeout(5000)});if(r.ok)showModels(await r.json());}catch(e){}finally{modelsBusy=false;}
}
$('select-model').onclick=async()=>{
  $('select-model').disabled=true;
  try{const r=await fetch('/api/gemini/models/select',{method:'POST',signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error();showModels(await r.json());}
  catch(e){$('model-selection-state').textContent='Não foi possível iniciar os testes.';$('select-model').disabled=false;}
};
