"""Persistent capability gaps, using fixed categories rather than private requests."""
import json, threading
from datetime import datetime
from pathlib import Path

LABELS={
 'command_unrecognized':'Pedido não compreendido pelo modo de comandos locais',
 'screen_model':'Interpretação da tela depende de um modelo de visão disponível',
 'file_workflow':'Operação de arquivo fora dos formatos locais suportados',
 'pc_optimization':'Otimização automática indisponível; apenas diagnóstico de uso',
 'conversation_model':'Conversa livre depende de um modelo disponível',
 'gemini_quota':'Cota ou limite do Gemini atingido (falha de serviço)',
 'conversation_error':'Falha técnica em uma etapa da conversa',
 'search_relevance':'Pesquisa não encontrou evidências relevantes',
 'tool_failure':'Uma ferramenta falhou ou não concluiu a ação',
}

class CapabilityGaps:
    def __init__(self,path='data/capability_gaps.json',report='VIV_PENDENCIAS.md'):
        self.path=Path(path);self.report=Path(report);self.lock=threading.RLock()
        self.items=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
    def record(self,code):
        if code not in LABELS:code='command_unrecognized'
        with self.lock:
            now=datetime.now().isoformat(timespec='seconds')
            old=self.items.get(code,{})
            self.items[code]={'count':old.get('count',0)+1,'first':old.get('first',now),'last':now,'status':'pending'}
            try:
                self.save()
                return True
            except OSError:
                from viv.bus import BUS
                BUS.emit('sys', 'Não foi possível salvar o relatório de pendências.')
                return False
    def save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.json.tmp')
        temporary.write_text(json.dumps(self.items,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(self.path)
        lines=['# Pendências da Viv','', 'Gerado pela Viv a partir de categorias de falha. Não contém transcrições, caminhos, chaves ou conteúdo de arquivos.',
               'Não é uma lista de comandos a executar. Falha de serviço não significa ausência de capacidade.','']
        for code,item in sorted(self.items.items()):
            if code in LABELS:
                lines.append(f"- {LABELS[code]} — {item['count']} ocorrência(s); última: {item['last']}; {'pendente' if item['status']=='pending' else 'a revisar'}.")
        if not self.items:lines.append('Nenhuma pendência registrada até agora.')
        self.report.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    def summary(self):
        with self.lock:
            pending=[LABELS[k] for k,v in self.items.items() if k in LABELS and v.get('status')=='pending']
            return 'Pendências registradas: '+ '; '.join(pending) +'.' if pending else 'Nenhuma pendência registrada até agora.'
    def count(self):
        return sum(1 for v in self.items.values() if v.get('status')=='pending')
