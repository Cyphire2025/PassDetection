"""Validate the delivered video/audio streams and sample actual decoded motion."""
from pathlib import Path
import subprocess,json,hashlib,sys
import numpy as np
ROOT=Path(__file__).resolve().parent.parent
BIN=Path(r'C:\Users\nipun\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1-full_build\bin')
def run(args):
    p=subprocess.run(args,capture_output=True)
    if p.returncode:raise RuntimeError(p.stderr.decode(errors='replace'))
    return p
results=[]
for f in sorted((ROOT/'videos').glob('*.mp4')):
    if len(sys.argv)>1 and not f.name.startswith(sys.argv[1]):continue
    meta=json.loads(run([str(BIN/'ffprobe.exe'),'-v','error','-show_streams','-show_format','-of','json',str(f)]).stdout)
    v=next(s for s in meta['streams'] if s['codec_type']=='video')
    a=next(s for s in meta['streams'] if s['codec_type']=='audio')
    checks={'duration_26s':abs(float(meta['format']['duration'])-26)<.05,'1080x1920':(v['width'],v['height'])==(1080,1920),'30fps':v['avg_frame_rate']=='30/1','780_frames':int(v['nb_frames'])==780,'h264_yuv420p':v['codec_name']=='h264' and v['pix_fmt']=='yuv420p','aac_48khz_stereo':a['codec_name']=='aac' and int(a['sample_rate'])==48000 and a['channels']==2}
    decoded=run([str(BIN/'ffmpeg.exe'),'-v','error','-i',str(f),'-f','null','-'])
    checks['full_decode_without_errors']=not decoded.stderr.strip()
    raw=run([str(BIN/'ffmpeg.exe'),'-v','error','-i',str(f),'-vf','fps=2,scale=108:192','-pix_fmt','rgb24','-f','rawvideo','-']).stdout
    frames=np.frombuffer(raw,np.uint8).reshape(-1,192,108,3)
    diff=np.abs(np.diff(frames.astype(np.float32),axis=0)).mean(axis=(1,2,3))
    checks['no_blank_sampled_frames']=bool(np.min(frames.mean(axis=(1,2,3)))>4)
    checks['visible_motion']=bool(np.count_nonzero(diff>.05)>len(diff)*.7)
    aud=run([str(BIN/'ffmpeg.exe'),'-v','error','-i',str(f),'-vn','-ac','1','-ar','48000','-f','f32le','-']).stdout
    signal=np.frombuffer(aud,np.float32)
    checks['audible_soundtrack']=bool(np.sqrt(np.mean(signal**2))>.015)
    checks['audio_not_clipped']=bool(np.max(np.abs(signal))<.999)
    item={'file':f.name,'checks':checks,'passed':all(checks.values()),'bytes':f.stat().st_size,'sha256':hashlib.sha256(f.read_bytes()).hexdigest(),'duration_seconds':float(meta['format']['duration']),'resolution':[v['width'],v['height']],'fps':30,'frames':int(v['nb_frames']),'audio_sample_rate':int(a['sample_rate']),'audio_channels':a['channels'],'sampled_motion_mean_pixel_change':float(diff.mean()),'audio_rms':float(np.sqrt(np.mean(signal**2))),'audio_peak':float(np.max(np.abs(signal)))}
    (ROOT/'qa'/f'{f.stem}-verification.json').write_text(json.dumps(item,indent=2))
    results.append(item)
    print(f"{'PASS' if item['passed'] else 'FAIL'} {f.name}: {json.dumps(checks)}")
if len(sys.argv)==1:(ROOT/'qa'/'delivery-verification.json').write_text(json.dumps(results,indent=2))
if not results or not all(r['passed'] for r in results):sys.exit(1)
