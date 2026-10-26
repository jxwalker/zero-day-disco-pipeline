"""Motion-graphics base for karaoke v1."""
import math, random
from PIL import Image, ImageDraw, ImageFont, ImageFilter
FD='/usr/share/fonts/truetype/sand-box/google/'
MONO=FD+'IBM Plex Mono/IBMPlexMono-SemiBold.ttf'; MONOB=FD+'IBM Plex Mono/IBMPlexMono-Bold.ttf'
SANS=FD+'Poppins/Poppins-Black.ttf'; SANSB=FD+'Poppins/Poppins-Bold.ttf'
_fc={}
def F(p,s):
    k=(p,int(s))
    if k not in _fc: _fc[k]=ImageFont.truetype(p,int(s))
    return _fc[k]
GREEN=(57,255,140); RED=(255,59,72); AMBER=(255,190,40); BLUE=(60,150,255); CY=(80,230,255); WH=(235,240,245); DIM=(120,135,150)
def base(W,H,col=(6,10,16)):
    im=Image.new('RGB',(W,H),col); d=ImageDraw.Draw(im)
    for y in range(0,H,4): d.line([(0,y),(W,y)],fill=tuple(max(0,c-3) for c in col))
    return im,d
def U(W,H): return min(W,H)/1080  # unit scale
def ctext(d,xy,s,font,fill,anchor='mm'): d.text(xy,s,font=font,fill=fill,anchor=anchor)

def term(W,H,t,dur,p):
    """p['lines']: list of (kind,text) kind 'cmd' typed, 'out' instant, 'big' """
    im,d=base(W,H,(8,12,10)); u=U(W,H)
    x0,y0=int(W*0.07),int(H*0.08) if H>W else int(H*0.08)
    bw=W-2*x0; bh=int(H*(0.52 if H>W else 0.62))
    d.rounded_rectangle([x0,y0,x0+bw,y0+bh],radius=int(18*u),fill=(14,18,16),outline=(50,60,55),width=3)
    d.rectangle([x0,y0,x0+bw,y0+int(54*u)],fill=(32,36,34))
    for i,c in enumerate([(255,95,86),(255,189,46),(39,201,63)]): d.ellipse([x0+20*u+i*34*u,y0+16*u,x0+42*u+i*34*u,y0+38*u],fill=c)
    ctext(d,(x0+bw/2,y0+27*u),p.get('title','user@prod: ~'),F(MONO,24*u),DIM)
    fs=p.get('fs',36)*u; f=F(MONO,fs); y=y0+80*u; cps=p.get('cps',28); clock=t*cps+4
    for kind,txt in p['lines']:
        if clock<=0: break
        col={'cmd':WH,'out':GREEN,'err':RED,'warn':AMBER,'dim':DIM,'cy':CY}.get(kind,WH)
        if kind=='cmd':
            n=int(min(len(txt),clock)); s='$ '+txt[:n]; clock-=len(txt)+6
            d.text((x0+28*u,y),s,font=f,fill=col)
            if n<len(txt) or clock<=0:
                if int(t*3)%2==0: d.rectangle([x0+28*u+d.textlength(s,font=f)+4,y+4,x0+28*u+d.textlength(s,font=f)+fs*0.6,y+fs*1.1],fill=GREEN)
                break
        else:
            d.text((x0+28*u,y),txt,font=f,fill=col); clock-=4
        y+=fs*1.45
        if y>y0+bh-fs*1.5: break
    if p.get('stamp') and t>dur*0.55:
        s=p['stamp']; a=min(1,(t-dur*0.55)*6); fb=F(SANS,p.get('stampsize',110)*u)
        layer=Image.new('RGBA',(W,H)); dl=ImageDraw.Draw(layer)
        tw=dl.textlength(s,font=fb); cx,cy=W/2,y0+bh*0.62
        dl.rounded_rectangle([cx-tw/2-30*u,cy-80*u,cx+tw/2+30*u,cy+80*u],radius=12,outline=p.get('stampcol',RED)+(int(255*a),),width=int(10*u))
        dl.text((cx,cy),s,font=fb,fill=p.get('stampcol',RED)+(int(255*a),),anchor='mm')
        layer=layer.rotate(-8,center=(cx,cy))
        im.paste(layer,(0,0),layer)
    return im


def countdown(W,H,t,dur,p):
    im,d=base(W,H,(20,4,6)); u=U(W,H); cy=H*0.28
    ctext(d,(W/2,cy-190*u),p.get('top','TIME TO EXPLOIT'),F(SANSB,64*u),RED)
    start=p.get('start',47*60); left=max(0,start-t*p.get('speed',60))
    s=f"{int(left//3600):02d}:{int(left%3600//60):02d}:{int(left%60):02d}"
    ctext(d,(W/2,cy),s,F(MONOB,200*u),RED if int(t*4)%2 else (255,120,120))
    ctext(d,(W/2,cy+170*u),p.get('sub',''),F(MONO,42*u),WH)
    for i in range(12):
        x=W*0.1+i*W*0.8/12; on=i<12*(1-t/dur)
        d.rectangle([x,cy+250*u,x+W*0.8/12-8,cy+290*u],fill=RED if on else (60,20,20))
    return im

def dash(W,H,t,dur,p):
    im,d=base(W,H,(6,10,18)); u=U(W,H); random.seed(p.get('seed',3))
    cols,rows=(3,6) if H>W else (6,3); gw=W*0.92/cols; gh=(H*0.58 if H>W else H*0.62)/rows; x0=W*0.04; y0=H*0.06
    names=p.get('tiles') or ['core-rtr-01','edge-fw-02','k8s-prod','dns-auth','lb-east','vpn-gw','db-primary','api-gw','bgp-peer','wan-sdx','auth-svc','cdn-pop','spine-03','leaf-12','ntp','syslog','etcd','mq-01']
    for i in range(cols*rows):
        c,r=i%cols,i//cols; x=x0+c*gw; y=y0+r*gh
        flip=p.get('flip',0.5); thr=(i*0.37%1)*0.5+flip*0.6
        mode=p.get('mode','r2g')
        bad = (t/dur < thr) if mode=='r2g' else (mode=='red' or (mode=='g2r' and t/dur>thr))
        col=RED if bad else GREEN
        d.rounded_rectangle([x+6,y+6,x+gw-6,y+gh-6],radius=10,fill=(20,26,36),outline=col,width=4)
        d.text((x+22*u,y+16*u),names[i%len(names)],font=F(MONOB,26*u),fill=WH)
        d.text((x+gw-22*u,y+16*u),'CRIT' if bad else 'OK',font=F(MONOB,26*u),fill=col,anchor='ra')
        pts=[]
        for k in range(24):
            v=0.5+0.35*math.sin(k*0.7+i+t*3*(1 if bad else 0.3))+(0.15*random.random())
            pts.append((x+20*u+k*(gw-40*u)/23,y+gh-20*u-v*(gh-80*u)*0.7))
        d.line(pts,fill=col,width=3)
    ok=sum(1 for i in range(cols*rows) if not ((t/dur<((i*0.37%1)*0.5+p.get('flip',0.5)*0.6)) if p.get('mode','r2g')=='r2g' else p.get('mode')=='red'))
    ctext(d,(W/2,y0+rows*gh+50*u),(p.get("footer") or f"HEALTHY {ok}/{cols*rows}"),F(MONOB,40*u),GREEN if ok>cols*rows/2 else RED)
    return im

def bluegreen(W,H,t,dur,p):
    im,d=base(W,H,(8,10,20)); u=U(W,H); k=min(1,max(0,(t/dur-0.25)/0.5))
    cy=H*0.27; bw=W*0.36; bh=230*u
    for i,(nm,ver,col,pct) in enumerate([(p.get('a','BLUE'),p.get('av','old'),BLUE,1-k),(p.get('b','GREEN'),p.get('bv','patched'),GREEN,k)]):
        x=W*0.07+i*(W*0.5); d.rounded_rectangle([x,cy-bh/2,x+bw,cy+bh/2],radius=20,fill=tuple(int(c*0.25) for c in col),outline=col,width=6)
        ctext(d,(x+bw/2,cy-50*u),nm,F(SANS,64*u),col); ctext(d,(x+bw/2,cy+20*u),ver,F(MONO,28*u),WH); ctext(d,(x+bw/2,cy+75*u),f"{pct*100:3.0f}% traffic",F(MONOB,34*u),WH)
    ctext(d,(W/2,cy-230*u),p.get('title','LIVE TRAFFIC SWITCH'),F(SANSB,50*u),WH)
    sw_y=cy+260*u; d.rounded_rectangle([W/2-150*u,sw_y-50*u,W/2+150*u,sw_y+50*u],radius=50*u,fill=(30,34,44),outline=DIM,width=3)
    kx=W/2-100*u+200*u*k; d.ellipse([kx-42*u,sw_y-42*u,kx+42*u,sw_y+42*u],fill=BLUE if k<0.5 else GREEN)
    ctext(d,(W/2,sw_y+110*u),p.get('sub',''),F(MONO,36*u),DIM)
    return im

def pipeline(W,H,t,dur,p):
    im,d=base(W,H,(10,10,18)); u=U(W,H)
    st=p.get('stages') or ['BUILD','TEST','CANARY','REVIEW','PROD']; n=len(st); prog=t/dur*n*1.1
    vert=H>W; ctext(d,(W/2,H*0.06),p.get('title','PIPELINE'),F(SANSB,52*u),WH)
    for i,s in enumerate(st):
        if vert: x,y,w,h=W*0.18,H*0.1+i*150*u,W*0.64,110*u
        else: x,y,w,h=W*0.04+i*W*0.19,H*0.3,W*0.17,140*u
        gate=i==p.get('gate',-1); done=prog>i+1; act=i<=prog<i+1
        col=GREEN if done else (AMBER if act else DIM)
        if i==1 and p.get('fail') and 0.3<t/dur<0.55: col=RED
        d.rounded_rectangle([x,y,x+w,y+h],radius=16,fill=(24,26,36),outline=col,width=6 if gate else 4)
        lab=s+(' ✓' if done else '')
        ctext(d,(x+w/2,y+h/2),s,F(SANS if gate else MONOB,(44 if gate else 38)*u*(0.75 if not vert else 1)),col)
        if gate and act: ctext(d,(x+w/2,y+h+28*u),'approve? [y/N]',F(MONO,30*u),AMBER)
    if p.get('fail') and 0.3<t/dur<0.6:
        ctext(d,(W/2,H*0.1+5*150*u+40*u if vert else H*0.6),p.get('failtext','FAIL'),F(SANS,58*u),RED)
    return im

