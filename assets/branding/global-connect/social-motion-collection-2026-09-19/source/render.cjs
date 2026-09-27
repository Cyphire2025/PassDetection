'use strict';
const fs=require('fs'),path=require('path'),{spawn}=require('child_process'),{once}=require('events');
const bundle=process.env.GCT_NODE_MODULES||'C:/Users/nipun/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules';
let canvas;try{canvas=require('@napi-rs/canvas')}catch{canvas=require(path.join(bundle,'@napi-rs/canvas'))}
const {createCanvas,loadImage,GlobalFonts}=canvas,C=require('./common.cjs');
GlobalFonts.registerFromPath('C:/Windows/Fonts/seguisb.ttf','GCT Display');
GlobalFonts.registerFromPath('C:/Windows/Fonts/segoeui.ttf','GCT Sans');
const ROOT=path.resolve(__dirname,'..'),DURATION=26,FPS=30;
const ffmpeg=process.env.FFMPEG_PATH||'C:/Users/nipun/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1-full_build/bin/ffmpeg.exe';
const argv=Object.fromEntries(process.argv.slice(2).map(s=>{const [k,...v]=s.replace(/^--/,'').split('=');return[k,v.length?v.join('='):true]}));
const filmFiles=fs.readdirSync(path.join(__dirname,'films')).filter(f=>f.endsWith('.cjs')).sort();
const selected=filmFiles.filter(f=>!argv.film||f.startsWith(argv.film.padStart(2,'0')));
const outputDirs=['videos','posters','qa','audio','assets'];outputDirs.forEach(d=>fs.mkdirSync(path.join(ROOT,d),{recursive:true}));
async function main(){
 const logoCopy=path.join(ROOT,'assets/company-logo-original.jpeg');
 if(!fs.existsSync(logoCopy))fs.copyFileSync(path.resolve(ROOT,'../global-connect-logo-original.jpeg'),logoCopy);
 const logo=await loadImage(logoCopy),lc=createCanvas(logo.width,logo.height),lx=lc.getContext('2d');lx.drawImage(logo,0,0);const ld=lx.getImageData(0,0,logo.width,logo.height).data;
 let bx=logo.width,by=logo.height,ex=0,ey=0;for(let y=0;y<logo.height;y++)for(let x=0;x<logo.width;x++){let i=(y*logo.width+x)*4;if(Math.min(ld[i],ld[i+1],ld[i+2])<150){bx=Math.min(bx,x);by=Math.min(by,y);ex=Math.max(ex,x);ey=Math.max(ey,y)}}
 const crop={x:bx-4,y:by-4,w:ex-bx+9,h:ey-by+9};
 function logoDraw(c,x,y,w){const h=w*crop.h/crop.w;c.drawImage(logo,crop.x,crop.y,crop.w,crop.h,x,y,w,h);return h}
 function end(c,t,film){const p=C.smooth(21.7,22.4,t);if(!p)return;C.withAlpha(c,p,()=>{C.background(c,t);C.withAlpha(c,.3,()=>{for(let i=0;i<5;i++){c.beginPath();c.ellipse(540,850,290+i*70,210+i*45,-.32+(t-22)*.055,0,Math.PI*2);c.strokeStyle=i===2?C.P.lime:C.P.teal;c.lineWidth=i===2?3:1;c.stroke()}});const enter=C.smooth(22,22.8,t);C.text(c,'EVERY DETAIL, CONNECTED.',540,525,29,C.P.lime,'center',600);C.rr(c,135,650+(1-enter)*40,810,380,34,'#ffffff');logoDraw(c,188,709+(1-enter)*40,704);C.lines(c,['Make your next','journey remarkable.'],540,1170,64,80,C.P.ivory,'center',700);C.rr(c,306,1373,468,84,42,C.P.lime);C.text(c,'LET’S PLAN IT TOGETHER',540,1426,24,C.P.navy,'center',700);C.text(c,'gctravels.in',540,1540,30,C.P.ivory,'center',500)})}
 function frame(c,t,film){c.save();C.background(c,t);c.save();film.draw(c,t,C);c.restore();if(t<22.4){C.withAlpha(c,1-C.smooth(21.7,22.4,t),()=>{C.rr(c,85,90,246,94,14,'#fff');logoDraw(c,101,104,214);C.text(c,'GLOBAL CONNECT TRAVELS',995,144,18,C.P.muted,'right',600);C.line(c,85,1657,995,1657,'#284554',2);C.line(c,85,1657,85+910*Math.min(t/22,1),1657,C.P.lime,3);C.text(c,'CORPORATE TRAVEL  /  INCENTIVES  /  EVENTS',85,1700,17,C.P.muted,'left',500)})}end(c,t,film);c.restore()}
 for(const filename of selected){
  const id=filename.replace('.cjs',''),film=require(path.join(__dirname,'films',filename));
  const width=Number(argv.width||1080),height=Math.round(width*16/9),cv=createCanvas(width,height),ctx=cv.getContext('2d');
  function draw(t){ctx.save();ctx.scale(width/1080,height/1920);frame(ctx,t,film);ctx.restore()}
  const times=[1.5,4.5,7.5,10,13,16,19,21,24];const sheet=createCanvas(1080,2040),sc=sheet.getContext('2d');sc.fillStyle='#071927';sc.fillRect(0,0,1080,2040);
  times.forEach((t,i)=>{draw(t);const x=(i%3)*360,y=Math.floor(i/3)*680;sc.drawImage(cv,x,y,360,640);C.text(sc,`${id.slice(0,2)} · ${t.toFixed(1)}s`,x+15,y+665,18,'#ffffff','left',500)});
  fs.writeFileSync(path.join(ROOT,'qa',id+'-contact-sheet.jpg'),sheet.toBuffer('image/jpeg',90));
  draw(2.5);fs.writeFileSync(path.join(ROOT,'posters',id+'.jpg'),cv.toBuffer('image/jpeg',94));
  fs.writeFileSync(path.join(ROOT,'qa',id+'-storyboard.json'),JSON.stringify({title:film.title,subtitle:film.subtitle,duration:DURATION,storyboard:film.storyboard},null,2));
  if(argv.preview!==undefined){console.log('PREVIEW_READY '+id);continue}
  const dest=path.join(ROOT,'videos',id+'.mp4'),aud=path.join(ROOT,'audio',id+'.wav');if(!fs.existsSync(aud))throw new Error('Missing original soundtrack '+aud);
  const args=['-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','rgba','-video_size',`${width}x${height}`,'-framerate',String(FPS),'-i','pipe:0','-i',aud,'-map','0:v:0','-map','1:a:0','-c:v','libx264','-preset','fast','-crf','18','-threads','2','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709','-colorspace','bt709','-c:a','aac','-b:a','192k','-af','loudnorm=I=-16:TP=-1.5:LRA=9','-t',String(DURATION),'-movflags','+faststart','-metadata',`title=${film.title} | Global Connect Travels`,'-metadata','comment=Original animated artwork and original synthesized soundtrack. Sole supplied visual asset: company logo.',dest];
  args.splice(args.indexOf('-af'),0,'-ar','48000');
  const p=spawn(ffmpeg,args,{stdio:['pipe','ignore','pipe'],windowsHide:true});let err='';p.stderr.on('data',b=>err+=b.toString());const finish=new Promise((res,rej)=>{p.once('error',rej);p.once('close',code=>code===0?res():rej(new Error(err||'ffmpeg '+code)))});p.stdin.on('error',()=>{});
  const start=Date.now();for(let f=0;f<DURATION*FPS;f++){draw(f/FPS);if(!p.stdin.write(cv.data()))await once(p.stdin,'drain');if(f%150===0)console.log(`${id} ${f}/${DURATION*FPS} ${((Date.now()-start)/1000).toFixed(1)}s`)}p.stdin.end();await finish;
  console.log('VIDEO_READY '+dest);console.log('RENDER_SECONDS '+((Date.now()-start)/1000).toFixed(1));
 }
}
main().catch(e=>{console.error(e);process.exitCode=1});
