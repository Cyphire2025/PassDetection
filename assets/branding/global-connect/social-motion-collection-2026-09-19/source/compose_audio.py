"""Original deterministic stereo scores: synthesized notes, percussion and transitions.
No samples, recordings, external music, or imitated artist compositions are used.
"""
from pathlib import Path
import numpy as np
import wave, json

ROOT=Path(__file__).resolve().parent.parent
SR=48000
DURATION=26

def hz(n):return 440*2**((n-69)/12)

def compose(index,stem):
    rng=np.random.default_rng(72819+index*873)
    track=np.zeros((SR*DURATION,2),dtype=np.float64)
    def add(sig,start,pan=0,gain=1):
        start=int(start*SR)
        if start>=len(track):return
        if start<0:sig=sig[-start:];start=0
        n=min(len(sig),len(track)-start)
        gains=np.array([np.sqrt((1-pan)/2),np.sqrt((1+pan)/2)])*gain
        track[start:start+n]+=sig[:n,None]*gains
    root=[50,55,57,52,53,48,55,50][index-1]
    # A distinct voicing and melody order for each of the eight scores.
    progressions=[[0,7,11,14],[9,12,16,19],[5,9,12,16],[7,11,14,19]]
    if index%2==0:progressions=[progressions[i] for i in [2,0,3,1]]
    beat=.5
    for bar in range(13):
        chord=progressions[(bar+index//3)%4]
        ts=bar*2
        tt=np.arange(int(SR*2.6))/SR
        env=np.minimum(tt/.3,1)*np.minimum((2.6-tt)/.9,1)
        for k,interval in enumerate(chord):
            f=hz(root+interval)
            phase=rng.random()*6.28
            tone=(np.sin(2*np.pi*f*tt+phase)+.30*np.sin(2*np.pi*f*2.002*tt)+.12*np.sin(2*np.pi*f*3*tt))
            tone+=.22*np.sin(2*np.pi*f*1.003*tt+1.2)
            add(tone*env,ts,pan=(k-1.5)*.3,gain=.028)
        # Rounded electric-pluck melody with octave interplay and stereo echoes.
        pattern=[0,2,1,3,2,1,3,0] if index%2 else [1,3,2,0,3,2,0,1]
        for step,k in enumerate(pattern):
            at=ts+step*.25
            if at>24.2:continue
            tt=np.arange(int(SR*.85))/SR
            f=hz(root+chord[k]+12+(12 if (bar+step+index)%9==0 else 0))
            env=(1-np.exp(-tt*550))*np.exp(-tt*5.8)
            tone=(np.sin(2*np.pi*f*tt)+.27*np.sin(2*np.pi*f*2*tt)*np.exp(-tt*9)+.10*np.sin(2*np.pi*f*3*tt))*env
            pan=np.sin(step*1.7+index)*.48
            add(tone,at,pan,.063)
            add(tone,at+.375,-pan,.020)
            add(tone,at+.75,pan,.008)
        # Soft pulse; deliberately restrained under the visual story.
        for k in range(4):
            at=ts+k*beat
            if at>24:continue
            tt=np.arange(int(SR*.25))/SR
            freq=48+70*np.exp(-tt*35)
            phase=2*np.pi*np.cumsum(freq)/SR
            kick=np.sin(phase)*np.exp(-tt*19)*(1-np.exp(-tt*650))
            add(kick,at,0,.115 if k%2==0 else .065)
            tt=np.arange(int(SR*.07))/SR
            noise=rng.standard_normal(len(tt));noise=np.diff(noise,prepend=noise[0])
            tick=noise*np.exp(-tt*90)*np.minimum(tt/.001,1)
            add(tick,at+.25,(-1 if k%2 else 1)*.42,.008)
            if k%2:
                tt=np.arange(int(SR*.16))/SR
                noise=rng.standard_normal(len(tt));noise=(noise+np.roll(noise,1)+np.roll(noise,2))/3
                clap=noise*np.exp(-tt*40)*(1-np.exp(-tt*800))
                add(clap,at,.15,.028)
    # Airy scene-change accents synthesized directly from noise.
    for switch in [5.5,11,16.5,22]:
        tt=np.arange(int(SR*.8))/SR
        noise=rng.standard_normal(len(tt))
        for _ in range(4):noise=(noise+np.roll(noise,1))/2
        env=np.sin(np.pi*tt/.8)**2
        add(noise*env,switch-.45,-.25,.028)
        add(noise*env,switch-.38,.25,.022)
    # New closing chord and fine high chime.
    tt=np.arange(int(SR*3.9))/SR
    for j,n in enumerate([root+12,root+19,root+23,root+26]):
        env=(1-np.exp(-tt*10))*np.exp(-tt*.8)
        add(np.sin(2*np.pi*hz(n)*tt)*env,22.05,(j-1.5)*.3,.06)
    # Small original diffuse reverb from staggered, cross-channel taps.
    dry=track.copy()
    for delay,gain in [(.113,.11),(.179,.085),(.271,.07),(.431,.05),(.619,.035)]:
        d=int(delay*SR);track[d:]+=dry[:-d,::-1]*gain
    fadein=np.minimum(np.arange(len(track))/SR/.24,1)
    fadeout=np.minimum((DURATION-np.arange(len(track))/SR)/1.15,1)
    track*=np.clip(fadein*fadeout,0,1)[:,None]
    track=np.tanh(track*1.7)
    track*=.84/max(np.max(np.abs(track)),1e-9)
    out=ROOT/'audio'/f'{stem}.wav'
    with wave.open(str(out),'wb') as w:
        w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR)
        w.writeframes((track*32767).astype('<i2').tobytes())
    return {'file':str(out.name),'duration':DURATION,'sample_rate':SR,'original_synthesis':True,'seed':72819+index*873}

if __name__=='__main__':
    (ROOT/'audio').mkdir(exist_ok=True)
    films=sorted((ROOT/'source'/'films').glob('*.cjs'))
    results=[compose(int(f.name[:2]),f.stem) for f in films]
    (ROOT/'qa'/'soundtrack-provenance.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
