'use strict';
const fs=require('node:fs');const path=require('node:path');const{spawn}=require('node:child_process');const{once}=require('node:events');
const{createCanvas}=require('@napi-rs/canvas');const{render,DURATION}=require('./scene.cjs');
const root=path.resolve(__dirname,'..'),args=process.argv.slice(2);const arg=(s,d)=>{const i=args.indexOf(s);return i>=0?args[i+1]:d;};
async function main(){
 if(args.includes('--stills')){
  const times=[0,4,8.4,11,16,20.3];
  // Each tile is 880 x 550 in a deliberately larger, legible contact sheet.
  const board=createCanvas(1800,1790),b=board.getContext('2d');b.fillStyle='#081b2d';b.fillRect(0,0,1800,1790);
  for(let i=0;i<times.length;i++){const frame=render(times[i],880,550),x=10+(i%2)*895,y=10+Math.floor(i/2)*594;b.drawImage(frame,x,y);b.fillStyle='#b9c9d6';b.font='18px Arial';b.fillText(`${times[i].toFixed(1)} s`,x+14,y+578);fs.writeFileSync(path.join(root,'qa',`frame-${i}.jpg`),frame.toBuffer('image/jpeg',94));}
  fs.writeFileSync(path.join(root,'qa','contact-sheet.jpg'),board.toBuffer('image/jpeg',94));
  fs.writeFileSync(path.join(root,'journey-film-poster.jpg'),render(0).toBuffer('image/jpeg',94));
  console.log('Contact sheet and poster ready.');return;
 }
 const width=+arg('--width','1600'),height=+arg('--height','1000'),fps=+arg('--fps','30'),crf=arg('--crf','23'),out=arg('--output',path.join(root,'journey-film-web.mp4'));
 const contain=args.includes('--contain');
 const renderFrame=time=>{
  if(!contain)return render(time,width,height);
  const scale=Math.min(width/1600,height/1000),artWidth=Math.round(1600*scale),artHeight=Math.round(1000*scale);
  const frame=createCanvas(width,height),ctx=frame.getContext('2d');ctx.fillStyle='#0b2239';ctx.fillRect(0,0,width,height);
  // Render geometry at its native output dimensions, then place without scaling.
  ctx.drawImage(render(time,artWidth,artHeight),Math.round((width-artWidth)/2),Math.round((height-artHeight)/2));return frame;
 };
 const ffmpeg=process.env.FFMPEG_PATH||'ffmpeg';const proc=spawn(ffmpeg,['-hide_banner','-loglevel','warning','-y','-f','rawvideo','-pixel_format','rgba','-video_size',`${width}x${height}`,'-framerate',String(fps),'-i','pipe:0','-an','-vf','scale=out_color_matrix=bt709:out_range=full,setparams=range=full:color_primaries=bt709:color_trc=iec61966-2-1:colorspace=bt709','-c:v','libx264','-preset','slow','-crf',crf,'-pix_fmt','yuvj420p','-color_range','pc','-color_primaries','bt709','-color_trc','iec61966-2-1','-colorspace','bt709','-movflags','+faststart','-metadata','title=Global Connect Travels | Move People. Create Moments.',out],{stdio:['pipe','ignore','pipe'],windowsHide:true});
 let err='';proc.stderr.on('data',d=>err+=d);proc.stdin.on('error',()=>{});const done=new Promise((res,rej)=>{proc.on('error',rej);proc.on('close',c=>c===0?res():rej(new Error(err)))}),start=Date.now();
 for(let i=0;i<DURATION*fps;i++){if(!proc.stdin.write(renderFrame(i/fps).data()))await once(proc.stdin,'drain');if(i%fps===0)console.log(`${i/fps}/${DURATION} seconds (${((Date.now()-start)/1000).toFixed(1)} seconds elapsed)`);}
 proc.stdin.end();await done;console.log(`Wrote ${out}`);
}
main().catch(e=>{console.error(e);process.exitCode=1;});
