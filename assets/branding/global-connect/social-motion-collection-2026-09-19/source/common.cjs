'use strict';
// Original drawing primitives for the GCT social motion collection.
const W=1080,H=1920;
const P={navy:'#091f32',ivory:'#f6f2e9',blue:'#267ec2',lime:'#b8d85a',teal:'#518f99',coral:'#dd916d',muted:'#97aebc'};
const clamp=(v,a=0,b=1)=>Math.max(a,Math.min(b,v));
const mix=(a,b,p)=>a+(b-a)*p;
const ease=p=>{p=clamp(p);return p*p*(3-2*p)};
const smooth=(a,b,t)=>ease((t-a)/(b-a));
function rr(c,x,y,w,h,r,fill,stroke=null,lw=2){if(w<=0||h<=0)return;c.beginPath();c.roundRect(x,y,w,h,Math.min(r,w/2,h/2));if(fill){c.fillStyle=fill;c.fill()}if(stroke){c.lineWidth=lw;c.strokeStyle=stroke;c.stroke()}}
function text(c,str,x,y,size=48,color=P.ivory,align='left',weight=600){weight=Math.max(100,Math.min(900,Math.round(weight/100)*100));c.fillStyle=color;c.font=`${weight} ${size}px "${weight>=600?'GCT Display':'GCT Sans'}"`;c.textAlign=align;c.textBaseline='alphabetic';c.fillText(str,x,y)}
function lines(c,arr,x,y,size=72,lineHeight=82,color=P.ivory,align='left',weight=700){arr.forEach((s,i)=>text(c,s,x,y+i*lineHeight,size,color,align,weight))}
function line(c,x1,y1,x2,y2,color,width=2){c.beginPath();c.moveTo(x1,y1);c.lineTo(x2,y2);c.strokeStyle=color;c.lineWidth=width;c.lineCap='round';c.stroke()}
function circle(c,x,y,r,fill,stroke=null,lw=2){if(r<=0)return;c.beginPath();c.arc(x,y,r,0,Math.PI*2);if(fill){c.fillStyle=fill;c.fill()}if(stroke){c.strokeStyle=stroke;c.lineWidth=lw;c.stroke()}}
function path(c,points,fill,stroke=null,lw=2){if(!points.length)return;c.beginPath();c.moveTo(...points[0]);points.slice(1).forEach(p=>c.lineTo(...p));if(fill){c.closePath();c.fillStyle=fill;c.fill()}if(stroke){c.lineWidth=lw;c.lineJoin='round';c.strokeStyle=stroke;c.stroke()}}
function withAlpha(c,a,fn){c.save();c.globalAlpha*=clamp(a);fn();c.restore()}
function withTransform(c,x,y,s,r,fn){c.save();c.translate(x,y);c.rotate(r);c.scale(s,s);fn();c.restore()}
function plane(c,x,y,s=1,r=0,color=P.ivory){withTransform(c,x,y,s,r,()=>{path(c,[[0,-66],[9,-48],[11,-10],[63,22],[64,36],[11,20],[9,51],[26,66],[24,73],[0,64],[-24,73],[-26,66],[-9,51],[-11,20],[-64,36],[-63,22],[-11,-10],[-9,-48]],color);line(c,0,-49,0,57,'#c7d9dd',2);rr(c,-6,-34,12,13,5,P.blue);})}
function person(c,x,y,s=1,color=P.blue){withTransform(c,x,y,s,0,()=>{circle(c,0,-36,12,P.coral);rr(c,-14,-19,28,43,11,color);line(c,-8,22,-10,53,P.ivory,8);line(c,8,22,10,53,P.ivory,8);line(c,-15,-7,-25,16,color,8);line(c,15,-7,25,13,color,8)})}
function star(c,x,y,r,color=P.lime){const p=[];for(let i=0;i<10;i++){let a=-Math.PI/2+i*Math.PI/5,rr=i%2?r*.43:r;p.push([x+Math.cos(a)*rr,y+Math.sin(a)*rr])}path(c,p,color)}
function arrow(c,x1,y1,x2,y2,color=P.lime,width=3){line(c,x1,y1,x2,y2,color,width);let a=Math.atan2(y2-y1,x2-x1);line(c,x2,y2,x2-15*Math.cos(a-.55),y2-15*Math.sin(a-.55),color,width);line(c,x2,y2,x2-15*Math.cos(a+.55),y2-15*Math.sin(a+.55),color,width)}
function background(c,t){let g=c.createLinearGradient(0,0,W,H);g.addColorStop(0,'#132f44');g.addColorStop(.5,P.navy);g.addColorStop(1,'#0a2536');c.fillStyle=g;c.fillRect(0,0,W,H);withAlpha(c,.065,()=>{for(let j=0;j<6;j++){c.beginPath();c.ellipse(935,1000,450+j*65,690+j*70,-.28+Math.sin(t*.1)*.015,0,Math.PI*2);c.strokeStyle=P.ivory;c.lineWidth=1;c.stroke()}});withAlpha(c,.14,()=>{for(let i=0;i<12;i++)circle(c,92+i*82,1715,1.8,P.ivory)})}
module.exports={W,H,P,clamp,mix,ease,smooth,rr,text,lines,line,circle,path,withAlpha,withTransform,plane,person,star,arrow,background};
