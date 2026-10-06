#!/usr/bin/env python3
"""PulseLab: loopback-only Verilog simulation workbench, Python standard library."""
import json, os, re, secrets, shutil, subprocess, tempfile, threading, time, webbrowser
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
TOKEN = secrets.token_urlsafe(32)
IDENT = r'[A-Za-z_][A-Za-z0-9_$]*'

def clean(s):
    return re.sub(r'/\*.*?\*/|//[^\n]*', ' ', s, flags=re.S)

def split(s, sep=','):
    result, start, depth = [], 0, 0
    for i, c in enumerate(s):
        if c in '([{': depth += 1
        elif c in ')]}': depth -= 1
        elif c == sep and depth == 0:
            result.append(s[start:i].strip()); start = i+1
    result.append(s[start:].strip())
    return [x for x in result if x]

def group(s, i):
    if s[i] != '(': raise ValueError('Expected parenthesis')
    depth=1
    for j in range(i+1,len(s)):
        if s[j]=='(': depth+=1
        elif s[j]==')':
            depth-=1
            if depth==0: return s[i+1:j], j+1
    raise ValueError('Unclosed module header')

def modules(files):
    found=[]
    for f in files:
        s=clean(f['text'])
        for m in re.finditer(r'\bmodule\s+('+IDENT+r')\b',s):
            end=s.find('endmodule',m.end())
            if end<0: raise ValueError('Missing endmodule for '+m[1])
            i=m.end()
            while s[i:i+1].isspace(): i+=1
            params=''
            if s[i:i+1]=='#':
                i+=1
                while s[i:i+1].isspace(): i+=1
                params,i=group(s,i)
            while s[i:i+1].isspace(): i+=1
            header=''
            if s[i:i+1]=='(': header,i=group(s,i)
            body=s[i:end]
            found.append({'name':m[1],'header':header,'params':params,'body':body})
    names=[m['name'] for m in found]
    if len(names)!=len(set(names)): raise ValueError('Duplicate module names across files')
    return found

def parameter_list(s):
    out=[]
    for x in split(s):
        if not x: continue
        if re.search(r'\btype\b',x): raise ValueError('Type parameters require Custom testbench mode')
        match=re.search(r'('+IDENT+r')\s*=\s*(.+)$',x,re.S)
        if not match: raise ValueError('Parameter has no supported default: '+x)
        out.append({'name':match[1],'value':match[2].strip()})
    return out

def analyze(files,top=None):
    ms=modules(files)
    if not ms: raise ValueError('No module found')
    if top and top not in [m['name'] for m in ms]:
        raise ValueError('Selected top module no longer exists. Clear/reselect the top after editing its name.')
    mod=next((m for m in ms if m['name']==top),ms[0])
    header=mod['header']; ports=[]; context=None
    ansi=bool(re.search(r'\b(input|output|inout)\b',header))
    declarations=split(header) if ansi else []
    if not ansi:
        for m in re.finditer(r'\b(input|output|inout)\b([^;]*);',mod['body']):
            declarations.extend(split(m[1]+' '+m[2]))
    for x in declarations:
        dm=re.match(r'(input|output|inout)\b\s*(.*)',x,re.S)
        if dm:
            direction=dm[1]; rest=dm[2].strip()
            rest=re.sub(r'\b(wire|reg|logic|bit|var)\b',' ',rest).strip()
            signed=bool(re.search(r'\bsigned\b',rest))
            rest=re.sub(r'\b(signed|unsigned)\b',' ',rest).strip()
            ranges=[]
            while rest.startswith('['):
                k=rest.find(']')
                if k<0: raise ValueError('Unclosed bus dimension')
                ranges.append(rest[:k+1]); rest=rest[k+1:].strip()
            context=(direction,' '.join(ranges),signed)
        else: rest=x
        if context is None: raise ValueError('Unsupported port declaration; use Custom testbench')
        nm=re.fullmatch(r'('+IDENT+r')\s*',rest)
        if not nm: raise ValueError('Automatic mode supports scalar and packed vector ports. Arrays, interfaces, user types or defaults need Custom testbench: '+x)
        direction,width,signed=context
        if direction=='inout': raise ValueError('Bidirectional ports require Custom testbench mode to control drive/release')
        ports.append({'name':nm[1],'direction':direction,'width':width,'signed':signed})
    if not ansi and header:
        order=[x.strip() for x in split(header)]
        if set(order)!=set(p['name'] for p in ports): raise ValueError('Could not resolve all non-ANSI ports; use Custom testbench')
        ports.sort(key=lambda p:order.index(p['name']))
    params=parameter_list(mod['params'])
    for m in re.finditer(r'\bparameter\s+([^;]*);',mod['body']): params+=parameter_list(m[1])
    locals_=[]
    for m in re.finditer(r'\blocalparam\s+([^;]*);',mod['body']): locals_+=parameter_list(m[1])
    return {'name':mod['name'],'modules':[m['name'] for m in ms],'ports':ports,'parameters':params,'locals':locals_}

def value(s):
    s=str(s).strip()
    if re.fullmatch(r'-?\d+',s): return s
    if re.fullmatch(r"(?:\d+)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|'[01xXzZ]",s): return s
    if re.fullmatch(r'0[xX][0-9a-fA-F]+',s): return "'h"+s[2:]
    raise ValueError('Invalid input value '+s+". Use decimal, 0xFF or 8\'b10101010")

def make_tb(a,cfg,duration,overrides):
    duration=int(duration)
    if not 1<=duration<=1000000: raise ValueError('Duration must be 1–1,000,000 ns')
    lines=['`timescale 1ns/1ps','module pulselab_tb;']
    for p in a['parameters']+a['locals']:
        expr=str(overrides.get(p['name'],p['value']))
        if re.search(r'[;`\n\r]',expr): raise ValueError('Invalid parameter expression')
        lines.append('localparam '+p['name']+' = '+expr+';')
    for p in a['ports']:
        lines.append(('reg ' if p['direction']=='input' else 'wire ')+('signed ' if p['signed'] else '')+p['width']+' '+p['name']+';')
    overrides_str=' #('+','.join('.'+p['name']+'('+p['name']+')' for p in a['parameters'])+')' if a['parameters'] else ''
    lines.append(a['name']+overrides_str+' dut ('+','.join('.'+p['name']+'('+p['name']+')' for p in a['ports'])+');')
    lines+=['initial begin $dumpfile("wave.vcd"); $dumpvars(0,pulselab_tb); end',f'initial begin #{duration}; $finish; end']
    for p in a['ports']:
        if p['direction']!='input': continue
        n=p['name']; c=cfg.get(n,{})
        role=c.get('role','constant'); init=value(c.get('initial','0'))
        lines.append('initial begin')
        lines.append(n+' = '+init+';')
        if role=='clock':
            if p['width']: raise ValueError('Clock must be a scalar: '+n)
            period=float(c.get('period',10))
            if period<0.002 or period>duration*2: raise ValueError('Clock period out of range')
            lines.append(f'forever #{period/2:g} {n} = ~{n};')
        elif role=='reset':
            at=float(c.get('release',12))
            if at<=0: raise ValueError('Reset release must be positive')
            lines.append(f'#{at:g} {n} = ~{n};')
        elif role=='counter':
            interval=float(c.get('interval',10)); offset=float(c.get('offset',2))
            if interval<=0 or offset<0: raise ValueError('Positive interval and nonnegative offset required')
            lines.append(f'#{offset:g}; forever begin #{interval:g} {n} = {n} + 1\'b1; end')
        elif role=='sequence':
            last=0
            for item in str(c.get('sequence','')).split(','):
                if not item.strip(): continue
                pair=item.split(':',1)
                if len(pair)!=2: raise ValueError('Sequence format: 0:0, 12:1, 22:0')
                at=float(pair[0]); val=value(pair[1])
                if at<last or at<0 or at>duration: raise ValueError('Sequence times must increase and fit duration')
                lines.append(f'#{at-last:g} {n} = {val};'); last=at
        elif role!='constant': raise ValueError('Unknown input role')
        lines.append('end')
    lines.append('endmodule')
    return '\n'.join(lines)+'\n'

def validate_files(files):
    if not 1<=len(files)<=100: raise ValueError('Provide 1–100 source/data files')
    seen=set()
    for f in files:
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',f['name']): raise ValueError('Use flat filenames with letters, numbers, dot, dash or underscore')
        if f['name'] in seen or f['name'] in ['_pulselab_tb.sv','sim.vvp','wave.vcd']: raise ValueError('Duplicate/reserved filename')
        seen.add(f['name'])
        if len(f['text'])>2000000: raise ValueError('File too large')

def execute(cmd,cwd,seconds,log):
    with open(log,'wb') as out:
        proc=subprocess.Popen(cmd,cwd=cwd,stdout=out,stderr=subprocess.STDOUT,start_new_session=True)
        deadline=time.monotonic()+seconds
        try:
            while proc.poll() is None:
                if time.monotonic()>deadline: raise ValueError('Run timed out; check for an infinite zero-delay loop or reduce duration')
                if Path(log).stat().st_size>2000000: raise ValueError('Too much console output')
                vcd=Path(cwd)/'wave.vcd'
                if vcd.exists() and vcd.stat().st_size>20000000: raise ValueError('Waveform exceeds 20 MB; shorten run or dump fewer signals')
                time.sleep(.05)
        finally:
            if proc.poll() is None:
                import signal
                os.killpg(proc.pid,signal.SIGKILL); proc.wait()
    return proc.returncode,Path(log).read_text(errors='replace')[:2000000]

def run(data):
    files=data['files']; validate_files(files)
    mode=data.get('mode','auto')
    if mode=='auto':
        a=analyze(files,data.get('top'))
        tb=make_tb(a,data.get('config',{}),data.get('duration',160),data.get('overrides',{})); top='pulselab_tb'
    else:
        tb=data.get('testbench',''); top=data.get('tbtop','tb')
        if not re.fullmatch(IDENT,top): raise ValueError('Invalid testbench module name')
    if not shutil.which('iverilog') or not shutil.which('vvp'): raise ValueError('Icarus missing. On your Mac run: brew install icarus-verilog')
    with tempfile.TemporaryDirectory(prefix='pulselab-') as td:
        for f in files: (Path(td)/f['name']).write_text(f['text'])
        (Path(td)/'_pulselab_tb.sv').write_text(tb)
        sources=[f['name'] for f in files if f['name'].endswith(('.v','.sv'))]+['_pulselab_tb.sv']
        rc,log=execute(['iverilog','-g2012','-Wall','-I.','-s',top,'-o','sim.vvp']+sources,td,30,Path(td)/'compile.log')
        if rc: return {'ok':False,'log':log,'tb':tb}
        rc,simlog=execute(['vvp','sim.vvp'],td,15,Path(td)/'run.log')
        vcd=Path(td)/'wave.vcd'
        return {'ok':rc==0,'log':log+simlog,'tb':tb,'vcd':vcd.read_text(errors='replace') if vcd.exists() else '', 'note':'' if vcd.exists() else 'No wave.vcd produced. Custom testbench: add $dumpfile("wave.vcd"); $dumpvars(0, '+top+');'}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def send(self,code,body,kind='application/json'):
        self.send_response(code); self.send_header('Content-Type',kind); self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff'); self.end_headers(); self.wfile.write(body)
    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}'): return self.send(403,b'Forbidden')
        if self.path=='/': return self.send(200,(ROOT/'index.html').read_bytes().replace(b'__TOKEN__',TOKEN.encode()),'text/html; charset=utf-8')
        self.send(404,b'Not found')
    def do_POST(self):
        if self.headers.get('X-PulseLab-Token')!=TOKEN: return self.send(403,b'Forbidden')
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=5000000: raise ValueError('Request too large or empty')
            data=json.loads(self.rfile.read(size))
            if self.path=='/analyze': validate_files(data['files']); result=analyze(data['files'],data.get('top'))
            elif self.path=='/generate': result={'tb':make_tb(analyze(data['files'],data.get('top')),data.get('config',{}),data.get('duration',160),data.get('overrides',{}))}
            elif self.path=='/run': result=run(data)
            else: raise ValueError('Unknown endpoint')
            self.send(200,json.dumps(result).encode())
        except Exception as e: self.send(400,json.dumps({'error':str(e)}).encode())

if __name__=='__main__':
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    url=f'http://127.0.0.1:{server.server_port}'
    print('PulseLab running at '+url+'\nKeep this terminal open. Ctrl+C stops it.',flush=True)
    threading.Timer(.5,lambda:webbrowser.open(url)).start()
    try: server.serve_forever()
    except KeyboardInterrupt: server.server_close()
