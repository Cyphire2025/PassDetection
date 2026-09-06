'use strict';
const fs = require('node:fs');
const path = require('node:path');
const {createCanvas} = require('@napi-rs/canvas');
const W=1600,H=1000,DURATION=24,TAU=Math.PI*2;
const bg='#0b2239', blue='#2078b8', lime='#a7cf49', ivory='#e9f1ed';
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const ease=v=>{v=clamp(v);return v*v*v*(v*(v*6-15)+10);};
const ramp=(t,a,b)=>ease((t-a)/(b-a));
const mix=(a,b,p)=>a+(b-a)*p;
const bez=(a,b,c,d,p)=>((1-p)**3*a+3*(1-p)**2*p*b+3*(1-p)*p*p*c+p**3*d);
const texture=createCanvas(2048,1024),tx=texture.getContext('2d');
tx.fillStyle='#277dad';tx.fillRect(0,0,2048,1024);
const geo=JSON.parse(fs.readFileSync(path.join(__dirname,'ne_110m_land.geojson'),'utf8'));
tx.fillStyle='#e6eeeb';
for(const f of geo.features){const polys=f.geometry.type==='Polygon'?[f.geometry.coordinates]:f.geometry.coordinates;for(const poly of polys){tx.beginPath();for(const ring of poly){ring.forEach(([lon,lat],i)=>{let x=(lon+180)/360*2048,y=(90-lat)/180*1024;i?tx.lineTo(x,y):tx.moveTo(x,y)});tx.closePath();}tx.fill('evenodd');}}
const tex=tx.getImageData(0,0,2048,1024).data;
// Orthographic textured sphere. Lighting is evaluated on the surface; no blur,
// postprocessing haze, displacement, depth-of-field or raster zoom animation.
const sphereSize=Number(process.env.SPHERE_SIZE||820),sphere=createCanvas(sphereSize,sphereSize),sc=sphere.getContext('2d');
const sdata=sc.createImageData(sphereSize,sphereSize),normals=[];
for(let y=0;y<sphereSize;y++)for(let x=0;x<sphereSize;x++){
 const nx=(x+.5-sphereSize/2)/(sphereSize/2-1),ny=(sphereSize/2-y-.5)/(sphereSize/2-1),d=nx*nx+ny*ny;
 if(d>1)continue;const nz=Math.sqrt(1-d),lat=Math.asin(ny),lon=Math.atan2(nx,nz);
 const light=clamp(nx*-.40+ny*.59+nz*.70),shade=.48+.56*light;
 const spec=Math.pow(Math.max(0,nx*-.24+ny*.35+nz*.907),30)*.20;
 normals.push([(y*sphereSize+x)*4,lon,clamp(Math.floor((Math.PI/2-lat)/Math.PI*1024),0,1023),shade,spec,Math.min(1,(1-Math.sqrt(d))*sphereSize/2)]);
}
function globeImage(yaw){
 const out=sdata.data;
 for(let i=0;i<normals.length;i++){const [off,lon,ty,shade,spec,edge]=normals[i];let u=((lon+yaw)/TAU+.5)%1;if(u<0)u+=1;const ti=(ty*2048+Math.floor(u*2048))*4;
 out[off]=Math.min(255,tex[ti]*shade+255*spec);out[off+1]=Math.min(255,tex[ti+1]*shade+255*spec);out[off+2]=Math.min(255,tex[ti+2]*shade+255*spec);out[off+3]=Math.round(edge*255);}
 sc.putImageData(sdata,0,0);return sphere;
}
function line(ctx,pts,color,width=1,closed=false){ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));if(closed)ctx.closePath();ctx.strokeStyle=color;ctx.lineWidth=width;ctx.stroke();}
function pathFill(ctx,pts,fill,stroke){ctx.beginPath();pts.forEach((p,i)=>i?ctx.lineTo(p[0],p[1]):ctx.moveTo(p[0],p[1]));ctx.closePath();ctx.fillStyle=fill;ctx.fill();if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=.8;ctx.stroke();}}
function ellipse(ctx,x,y,rx,ry,fill,stroke,width=1){ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,TAU);if(fill){ctx.fillStyle=fill;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=width;ctx.stroke();}}
// A small retained mesh renderer keeps architecture, seats and aircraft crisp.
function makeWorld(ctx,t,size=1){
 const yaw=-.48+.06*Math.sin(t/DURATION*TAU),sy=Math.sin(yaw),cy=Math.cos(yaw),pitch=.51;
 const faces=[];
 // Width and vertical presence grow together. A restrained depth expansion
 // keeps the larger campus/auditorium naturally seated on the same plinth.
 const proj=(x,y,z)=>{x*=size;y*=size;z*=1+(size-1)*.18;let px=x*cy-z*sy,pz=x*sy+z*cy;return [800+px,696+pz*Math.sin(pitch)-y*Math.cos(pitch),pz*Math.cos(pitch)+y*Math.sin(pitch)];};
 const poly=(v,c,depth)=>{let pts=v.map(v=>proj(...v));faces.push({pts,c,d:depth===undefined?pts.reduce((s,p)=>s+p[2],0)/pts.length:depth});};
 const box=(x,y,z,w,h,d,c={top:'#dce9e9',front:'#8bafb9',side:'#457a91'})=>{
   if(h<.5)return;
   poly([[x,y+h,z],[x+w,y+h,z],[x+w,y+h,z+d],[x,y+h,z+d]],c.top);
   poly([[x,y,z+d],[x+w,y,z+d],[x+w,y+h,z+d],[x,y+h,z+d]],c.front);
   poly([[x+w,y,z],[x+w,y,z+d],[x+w,y+h,z+d],[x+w,y+h,z]],c.side);
   poly([[x,y,z],[x,y,z+d],[x,y+h,z+d],[x,y+h,z]],c.side);
 };
 const person=(x,y,z,s=1,standing=false,seed=0)=>{const at=proj(x,y,z);s*=size;faces.push({d:at[2]+(standing?28:38)*s,person:true,at,s,standing,seed});};
 const draw=()=>{faces.sort((a,b)=>a.d-b.d);for(const f of faces){if(!f.person){pathFill(ctx,f.pts,f.c);continue;}const[x,y]=f.at,s=f.s;ctx.save();ctx.translate(x,y);ctx.scale(s,s);const sway=Math.sin(t*.7+f.seed)*.6;
   if(f.standing){line(ctx,[[-4,0],[-4,-19]],'#12344d',5);line(ctx,[[4,0],[4,-19]],'#1a4059',5);}
   const base=f.standing?-16:-30,coat=f.seed%5===0?'#b4cc9a':f.seed%3===0?'#c5dcdf':'#376a8b';
   pathFill(ctx,[[-9,base],[-8+sway,base-21],[-5+sway,base-26],[5+sway,base-26],[9+sway,base-20],[9,base]],coat);
   const head=ctx.createRadialGradient(-2+sway,base-34,0,1+sway,base-31,7);head.addColorStop(0,f.seed%3===0?'#dabd9d':'#ba9779');head.addColorStop(1,f.seed%3===0?'#a9876b':'#7e6652');
   ellipse(ctx,sway,base-33,6,7,head);line(ctx,[[-7,base-21],[-10,base-6]],coat,4);line(ctx,[[7,base-21],[10,base-6]],coat,4);ctx.restore();}};
 return {proj,poly,box,person,draw};
}
function platform(ctx,t){
 const g=ctx.createLinearGradient(0,656,0,856);g.addColorStop(0,'#536a74');g.addColorStop(1,'#293f4b');
 const top=ctx.createLinearGradient(320,562,1290,850);top.addColorStop(0,'#88989e');top.addColorStop(.58,'#6b7e85');top.addColorStop(1,'#506974');
 ellipse(ctx,800,758,526,133,'#071c30');
 ellipse(ctx,800,735,506,150,'#344f5c','#728a96',1.1);
 ellipse(ctx,800,722,504,150,g,'#81959d',1.1);
 ctx.fillStyle=g;ctx.fillRect(296,699,1008,20);
 // Segmented physical rim: three stacked material bands and recessed seams.
 for(let i=0;i<14;i++){
  const a=.04+i*(Math.PI-.08)/14,b=a+(Math.PI-.08)/14-.022;
  ctx.beginPath();ctx.ellipse(800,722,505,150,0,a,b);ctx.strokeStyle=i%2?'#90a4ad':'#6c8794';ctx.lineWidth=5;ctx.stroke();
  line(ctx,[[800+505*Math.cos(a),706+150*Math.sin(a)],[800+505*Math.cos(a),733+150*Math.sin(a)]],'#3d5968',1.2);
 }
 ctx.beginPath();ctx.ellipse(800,730,506,150,0,.035,Math.PI-.035);ctx.strokeStyle='#b1c0c5';ctx.lineWidth=1.1;ctx.stroke();
 ellipse(ctx,800,699,504,150,top,'#d5e0df',1.6);
 // Low-contrast annular inlays suggest a precision navigation instrument.
 for(let i=0;i<6;i++){
  const a=i*TAU/6+.065,b=(i+1)*TAU/6-.065;
  ctx.beginPath();ctx.ellipse(800,699,476,135,0,a,b);ctx.ellipse(800,699,456,129,0,b,a,true);ctx.closePath();ctx.fillStyle=i%2?'rgba(229,237,233,.075)':'rgba(39,71,88,.08)';ctx.fill();
 }
 ellipse(ctx,800,699,468,132,null,'#98a9ae',1);
 ellipse(ctx,800,699,398,111,null,'#81969e',1);
 // Fine machined notches, restrained and spatial rather than particle clutter.
 for(let i=0;i<96;i++){const a=i/96*TAU;const r1=486,r2=i%8===0?469:i%4===0?475:481;line(ctx,[[800+Math.cos(a)*r1,699+Math.sin(a)*r1*.285],[800+Math.cos(a)*r2,699+Math.sin(a)*r2*.285]],i%8===0?'#d4dddd':'#9badb1',i%8===0?1.2:.8);}
 // An inset compass rose and three waypoints are engraved into the surface.
 ellipse(ctx,800,780,69,20,null,'rgba(45,75,91,.40)',1);
 ellipse(ctx,800,780,61,17,null,'rgba(228,237,232,.24)',.8);
 pathFill(ctx,[[800,759],[810,777],[857,780],[810,783],[800,801],[790,783],[743,780],[790,777]],'#607984');
 pathFill(ctx,[[800,759],[800,780],[790,777]],'#d7e2dc');
 pathFill(ctx,[[800,780],[800,801],[810,783]],'#3c5d70');
 ellipse(ctx,800,780,5.5,2,'#b0ca89');
 for(const a of [.47,1.55,2.68]){
  const x=800+428*Math.cos(a),y=699+120*Math.sin(a);
  ellipse(ctx,x,y,17,5.8,'#637d88','#b2c3c8',.8);
  ellipse(ctx,x,y,9,3.1,null,'#dce7e0',.9);ellipse(ctx,x,y,3.4,1.3,a<1?lime:'#dde7e1');
 }
 const phase=t/DURATION*TAU;
 ctx.beginPath();ctx.ellipse(800,700,505,150,0,phase+.15,phase+.85);ctx.strokeStyle=lime;ctx.lineWidth=2.6;ctx.stroke();
}
function aircraft(ctx,x,y,angle,scale=1){
 ctx.save();ctx.translate(x,y);ctx.rotate(angle);ctx.scale(scale,scale);
 // Bespoke swept-wing aircraft, geometric upper and shaded lower fuselage.
 pathFill(ctx,[[53,0],[27,-7],[4,-8],[-15,-43],[-29,-44],[-17,-7],[-43,-5],[-53,-18],[-63,-18],[-59,0],[-63,18],[-53,18],[-43,5],[-17,7],[-29,44],[-15,43],[4,8],[27,7]],'#edf4f1');
 pathFill(ctx,[[53,0],[27,7],[4,8],[-15,43],[-29,44],[-17,7],[-43,5],[-59,0]],'#aac2ce');
 pathFill(ctx,[[32,-4],[43,0],[32,3],[25,3],[25,-3]],'#32617d');
 line(ctx,[[-46,0],[25,0]],'#8aadb9',1.2);
 pathFill(ctx,[[-56,-1],[-49,-23],[-39,-23],[-44,-1]],lime);
 ctx.restore();
}
function sphereRoutes(ctx,cx,cy,r,t,strength=1){
 ctx.save();ctx.globalAlpha=strength;
 // Closed elliptical global trajectories with a genuinely moving aircraft.
 ctx.translate(cx,cy);ctx.rotate(-.33);
 ctx.beginPath();ctx.ellipse(0,14,r*1.36,r*.42,0,Math.PI,TAU);ctx.strokeStyle='#407b9a';ctx.lineWidth=1.3;ctx.stroke();
 const a=t/DURATION*TAU+.56,px=Math.cos(a)*r*1.36,py=14+Math.sin(a)*r*.42;
 if(Math.sin(a)<0)aircraft(ctx,px,py,Math.atan2(Math.cos(a)*r*.42,-Math.sin(a)*r*1.36),Math.max(.45,r/270)*.85);
 ctx.restore();
}
function sphereFrontRoute(ctx,cx,cy,r,t,strength=1){
 ctx.save();ctx.globalAlpha=strength;ctx.translate(cx,cy);ctx.rotate(-.33);
 ctx.beginPath();ctx.ellipse(0,14,r*1.36,r*.42,0,0,Math.PI);ctx.strokeStyle=lime;ctx.lineWidth=2;ctx.stroke();
 const a=t/DURATION*TAU+.56,px=Math.cos(a)*r*1.36,py=14+Math.sin(a)*r*.42;
 const tangent=Math.atan2(Math.cos(a)*r*.42,-Math.sin(a)*r*1.36);
 if(Math.sin(a)>=0)aircraft(ctx,px,py,tangent,Math.max(.45,r/270)*.85);
 ctx.restore();
}
function globe(ctx,x,y,r,t){
 sphereRoutes(ctx,x,y,r,t);ctx.drawImage(globeImage(.76+t/DURATION*TAU),x-r,y-r,r*2,r*2);
 // Thin visible equator/meridian arcs communicate projection and scale.
 ctx.save();ctx.translate(x,y);ctx.beginPath();ctx.arc(0,0,r-.7,0,TAU);ctx.clip();
 ctx.strokeStyle='rgba(187,225,230,.12)';ctx.lineWidth=.7;
 for(let v of [-.58,0,.58]){const rr=r*Math.sqrt(1-v*v);ctx.beginPath();ctx.ellipse(0,r*v,rr,rr*.1,0,0,TAU);ctx.stroke();}
 ctx.restore();sphereFrontRoute(ctx,x,y,r,t);
}
function tree(world,x,z,h=42){
 world.box(x-2,0,z-2,4,h*.7,4,{top:'#87a070',front:'#647958',side:'#3b604a'});
 world.box(x-12,h*.45,z-12,24,h*.45,24,{top:'#b4d878',front:'#729d53',side:'#527d43'});
 world.box(x-9,h*.8,z-9,18,h*.24,18,{top:'#c0dc8a',front:'#86ac5e',side:'#527d43'});
}
function hospitality(ctx,t,p){
 if(p<.001)return;const w=makeWorld(ctx,t,1+.18*ease(p));const c={top:'#e1eeef',front:'#93b8c8',side:'#406e89'};
 // Campus paving and three shallow approach steps rise from the shared plinth.
 w.box(-155,0,-190,465,10*p,355,{top:'#43647b',front:'#23465e',side:'#183d56'});
 for(let i=0;i<3;i++)w.box(-135-i*6,10*p,147+i*13,275+i*12,(3-i)*7*p,14,{top:'#a8c1c8',front:'#668c9e',side:'#52758d'});
 const blocks=[[-60,-144,124,298,94],[80,-178,137,362,104],[-105,-15,250,110,110]];
 blocks.forEach(([x,z,bw,bh,bd],bi)=>{
   const q=ease(clamp(p*1.4-bi*.13));const h=bh*q;if(h<2)return;
   w.box(x,10*p,z,bw,h,bd,c);
   // Recessed window bays are individual architectural planes, not a texture.
   for(let row=0;row<Math.floor(bh/36)-1;row++)for(let col=0;col<Math.floor(bw/22)-1;col++){
    const yy=31+row*34;if(yy+19>h)continue;
    w.poly([[x+15+col*23,yy,z+bd+.2],[x+29+col*23,yy,z+bd+.2],[x+29+col*23,yy+22,z+bd+.2],[x+15+col*23,yy+22,z+bd+.2]],(col+row)%6===0?'#e3cfa2':(col+row)%4===0?'#90bbc7':'#214d6b',w.proj(x+bw/2,10*p+h/2,z+bd)[2]+.5);
   }
   // Long glazed corner bays and light stone piers give the towers depth.
   if(bi<2){for(let k=0;k<3;k++){const zz=z+12+k*24;w.poly([[x-.2,31,zz],[x-.2,h-15,zz],[x-.2,h-15,zz+14],[x-.2,31,zz+14]],k===0?'#517d92':'#1c4c6c',w.proj(x,10*p+h/2,z+bd/2)[2]+.2);}}
   w.box(x-5,10*p+h-8,z-5,bw+10,8,bd+10,{top:'#f0f5ed',front:'#b2ccd1',side:'#7293a7'});
   if(bi===0){
    // A planted rooftop lounge with a precise louvred pergola.
    w.box(x+10,10*p+h,z+12,bw-20,3,bd-24,{top:'#9ba98e',front:'#74867a',side:'#5b746c'});
    for(let k=0;k<6;k++)w.box(x+12+k*17,10*p+h+22*q,z+8,5,3,bd-16,{top:'#f1eee1',front:'#b4c8c5',side:'#809d9d'});
    for(let xx of [x+13,x+bw-15])for(let zz of [z+11,z+bd-14])w.box(xx,10*p+h,zz,3,22*q,3,{top:'#e7eeeb',front:'#a9c5ca',side:'#7398a7'});
    for(let k=0;k<3;k++)w.box(x+5+k*40,10*p+h,z+bd-9,34,9*q,7,{top:'#a7c36d',front:'#7d9d58',side:'#587b44'});
   }
   if(bi===1){
    w.box(x+14,10*p+h,z+14,bw-30,15*q,bd-28,{top:'#c9e0e0',front:'#6e99ac',side:'#375d7a'});
    for(let k=0;k<7;k++)w.box(x+12+k*18,10*p+h+15*q,z+10,6,3,bd-20,{top:'#eaf2ed',front:'#a4c5cc',side:'#688c9e'});
   }
   if(bi===2){
    for(let k=0;k<5;k++){w.box(x+6+k*49,10*p+h,z+bd-14,42,10*q,10,{top:'#abc976',front:'#80994f',side:'#526e3e'});}
    for(let k=0;k<3;k++)w.box(x+25+k*70,10*p+h,z+20,36,8*q,18,{top:'#cfdecf',front:'#91a88d',side:'#718d7c'});
   }
 });
 // Glass entrance and dramatically projecting hospitality canopy.
 w.box(-65,10*p,70,166,78*p,20,{top:'#4a97b0',front:'#164464',side:'#245773'});
 for(let j=0;j<5;j++)w.box(-60+j*32,10*p,92,2,73*p,2,{top:'#dedfc5',front:'#dad4ac',side:'#8eacb9'});
 w.box(-110,86*p,64,270,9*p,98,{top:'#e7f0e8',front:'#a2c0c4',side:'#5c869b'});
 for(let x of [-98,-40,78,137])w.box(x,10*p,143,4,76*p,4,{top:'#dbece8',front:'#a6c2c8',side:'#5a8094'});
 // A few coordinated arrivals make the architecture a hospitality destination.
 w.person(-75,18*p,166,.82*p,true,2);w.person(-23,18*p,165,.84*p,true,7);w.person(38,17*p,161,.8*p,true,3);
 for(let [x,z] of [[275,-130],[267,-50],[265,38],[-175,20],[-185,99]])tree(w,x,z,50*p);
 w.draw();
 // Aircraft crosses behind the destination, visually carrying the journey on.
 const f=(t-6)/7;const x=mix(250,1360,f),y=300-60*Math.sin(f*Math.PI);
 if(f>0&&f<1){ctx.globalAlpha=Math.sin(f*Math.PI)*.7;aircraft(ctx,x,y,-.06,.42);ctx.globalAlpha=1;}
}
function events(ctx,t,p){
 if(p<.001)return;const w=makeWorld(ctx,t,1+.20*ease(p));const y=14*p;
 w.box(-285,0,-182,570,y,372,{top:'#496c84',front:'#2f5873',side:'#22485f'});
 // Stage is an architectural crescent assembled from aligned vertical fins.
 w.box(-235,y,-162,470,25*p,140,{top:'#d7e7e6',front:'#91b7c3',side:'#547d92'});
 for(let i=0;i<3;i++)w.box(-218-i*8,y,-23+i*9,436+i*16,(3-i)*7*p,10,{top:'#c8dedf',front:'#759eaf',side:'#4c728d'});
 // Layered screen surround and illuminated architectural wings.
 w.box(-205,y+25*p,-169,410,198*p,13,{top:'#dcebe9',front:'#527e98',side:'#315a78'});
 w.box(-190,y+25*p,-159,380,184*p,12,{top:'#7fb4c8',front:'#124775',side:'#28617f'});
 for(let i=0;i<11;i++){
   const xx=-250+i*47,hh=(190+26*Math.cos((i-5)/5*Math.PI/2))*p;
   w.box(xx,y,-177+Math.abs(i-5)*7,8,hh,12,{top:'#e2eee7',front:i%2?'#9ac4c9':'#d2e4df',side:'#719caf'});
 }
 // Screen: moving lime ribbons represent connections, no distracting text.
 for(let i=0;i<3;i++){
   const phase=(t*.35+i*.55),points=[];
   for(let j=0;j<=30;j++){let x=-165+j*11,yy=y+(80+i*34+14*Math.sin(j*.13+phase))*p;points.push([x,yy,-145]);}
   const pts=points.map(v=>w.proj(...v));
   // Queued thin quads keep screen strokes at the proper scene depth.
   for(let j=0;j<points.length-1;j++){let a=points[j],b=points[j+1];w.poly([a,b,[b[0],b[1]+2*p,b[2]],[a[0],a[1]+2*p,a[2]]],i===1?'#b4d96f':'#548caa',w.proj(0,y+117*p,-147)[2]+1);}
 }
 // Speakers, central lectern and two understated side towers.
 for(let x of [-246,226])w.box(x,y,-70,19,85*p,28,{top:'#305673',front:'#102e47',side:'#22475f'});
 w.box(-26,y+25*p,-52,33,49*p,24,{top:'#edf4e9',front:'#aac8ce',side:'#547f98'});
 w.person(-9,y+25*p,-70,1.3*p,true,0);w.person(104,y+25*p,-46,1.2*p,true,2);
 // Coordinated rows of bespoke seats: entering from the floor with a ripple.
 for(let row=0;row<4;row++)for(let col=0;col<9;col++){
   if(col===4)continue;const q=ease(clamp(p*1.7-row*.13-Math.abs(col-4)*.025));if(q<.01)continue;
   const x=-205+col*49,z=8+row*44;const mat=(row+col)%6===0?{top:'#c1df80',front:'#8aaa54',side:'#607e43'}:{top:'#c4dce0',front:'#6d9bb0',side:'#446d88'};
   w.box(x,y,z,28,19*q,29,mat);w.box(x,y+19*q,z+22,28,30*q,7,mat);
   for(let side of [0,25])w.box(x+side,y,z+2,3,26*q,25,{top:'#7299ab',front:'#3b6681',side:'#264960'});
   w.person(x+14,y,z+12,.95*q,false,row*9+col);
 }
 w.draw();
}
function render(t,width=W,height=H){
 t=((t%DURATION)+DURATION)%DURATION;
 const canvas=createCanvas(width,height),ctx=canvas.getContext('2d');ctx.scale(width/W,height/H);ctx.fillStyle=bg;ctx.fillRect(0,0,W,H);
 // Edge color remains exact; all scene elements stay within a generous safe area.
 platform(ctx,t);
 const destination=ramp(t,5.6,7.6)*(1-ramp(t,12.0,14.0));
 const event=ramp(t,12.3,14.4)*(1-ramp(t,19.0,21.3));
 const small=ramp(t,5.3,7.6)*(1-ramp(t,19.0,21.5));
 const cx=mix(800,453-8*destination-26*event,small),cy=mix(404,566,small),r=mix(278,93,small);
 // When globe is small it is the campus welcome sculpture. It floats very
 // gently over a crisp pedestal, while the geography makes one full rotation.
 if(small>.02){ellipse(ctx,cx,690,100*small,28*small,'#59717b','#a9bbc0');ellipse(ctx,cx,680,100*small,28*small,'#9cafb5','#e1e9e5');}
 globe(ctx,cx,cy+3*Math.sin(TAU*t/DURATION),r,t);
 hospitality(ctx,t,destination);events(ctx,t,event);
 // Single route path through the pavilion ties every chapter to one journey.
 ctx.save();ctx.beginPath();ctx.ellipse(800,699,441,122,0,.08,Math.PI-.08);ctx.strokeStyle='rgba(163,205,81,.62)';ctx.lineWidth=1.1;ctx.stroke();
 const a=TAU*((t/8)%1),px=800+441*Math.cos(a),py=699+122*Math.sin(a);
 ellipse(ctx,px,py,4,2.3,lime);ctx.restore();
 return canvas;
}
module.exports={render,DURATION,W,H};
