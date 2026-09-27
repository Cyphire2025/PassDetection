'use strict';

const title='From Empty Venue to Big Moment';
const subtitle='Spaces become experiences, one detail at a time.';
const storyboard=[
  {time:'0–5.5',scene:'An original architectural room and floor grid draw themselves into view.'},
  {time:'5.5–11',scene:'A stage lifts from the plan; a backdrop, screen and layered risers assemble in perspective.'},
  {time:'11–16.5',scene:'Banquet tables, chairs, flowers, light trusses and entrance details take their places.'},
  {time:'16.5–22',scene:'Guests arrive, the beams sweep and the venue becomes a luminous event.'},
  {time:'22–26',scene:'Shared Global Connect Travels logo and enquiry end card.'}
];

function draw(ctx,t,C){
  const {P,clamp,mix,ease,smooth,text,lines,rr,line,circle,path,withAlpha,person,star}=C;
  const TAU=Math.PI*2;
  ctx.fillStyle=P.navy;ctx.fillRect(0,0,1080,1920);
  const stage=smooth(5.5,8.7,t), furnishing=smooth(11.1,14.9,t), people=smooth(16.6,19.6,t);
  const h=t<5.5?0:t<11?1:t<16.5?2:3;
  const starts=[0,5.5,11,16.5];
  const labels=['THE FIRST SKETCH','THE SPACE TAKES SHAPE','EVERY DETAIL HAS A PLACE','THE BIG MOMENT'];
  const headlines=[['An empty space.','A world of possibility.'],['Build the setting.','Set the anticipation.'],['Bring the details','beautifully together.'],['Then the room','comes alive.']];
  const footers=[['Every remarkable gathering begins here.','With a vision worth bringing to life.'],['A stage for your story.','A setting for people to connect.'],['The welcome. The seating. The atmosphere.','Thoughtfully brought together.'],['Conferences. Celebrations. Shared experiences.','Your occasion, brought to life.']];
  withAlpha(ctx,smooth(starts[h],starts[h]+.55,t),()=>{
    text(ctx,labels[h],88,285,24,P.lime,'left',700);
    lines(ctx,headlines[h],85,378,65,79,P.ivory,'left',700);
    text(ctx,footers[h][0],88,1470,36,P.ivory,'left',500);
    text(ctx,footers[h][1],88,1520,34,P.muted,'left',400);
  });

  // A full architectural room keeps the same perspective throughout the film.
  // Floor maps normalized plan coordinates to a trapezoid, back to front.
  function project(u,v){return {x:mix(284,129,v)+u*mix(512,822,v),y:mix(986,1364,v)};}
  const plan=smooth(.2,2.5,t);
  withAlpha(ctx,plan,()=>{
    // Architectural massing: back wall, side walls, floor and fine trim.
    path(ctx,[[129,745],[284,640],[796,640],[951,745],[951,1364],[129,1364]],'#0d293e');
    path(ctx,[[284,640],[796,640],[796,986],[284,986]],'#14364b');
    path(ctx,[[129,745],[284,640],[284,986],[129,1364]],'#102f44');
    path(ctx,[[796,640],[951,745],[951,1364],[796,986]],'#17394c');
    path(ctx,[[284,986],[796,986],[951,1364],[129,1364]],'#15364b');
    // Blueprint perimeter draws progressively on first reveal.
    const perimeter=[[129,1364],[129,745],[284,640],[796,640],[951,745],[951,1364],[129,1364]];
    const progress=clamp((t-.2)/2.8);
    ctx.save();ctx.strokeStyle=mixColor('#518f99','#376478',stage);ctx.lineWidth=2;
    ctx.beginPath();let total=perimeter.length-1;for(let k=0;k<total;k++){const p=clamp(progress*total-k);if(!p)break;ctx.moveTo(...perimeter[k]);ctx.lineTo(mix(perimeter[k][0],perimeter[k+1][0],p),mix(perimeter[k][1],perimeter[k+1][1],p));}ctx.stroke();ctx.restore();
    for(let i=0;i<=8;i++){
      const a=project(i/8,0),b=project(i/8,1);
      line(ctx,a.x,a.y,b.x,b.y,'#2a5166',1);
    }
    for(let i=0;i<=7;i++){
      const a=project(0,i/7),b=project(1,i/7);
      line(ctx,a.x,a.y,b.x,b.y,'#2a5166',1);
    }
    // Vertical interior wall panels remain as stage dressing.
    for(let i=1;i<8;i++)line(ctx,284+i*64,640,284+i*64,986,'#23465a',1);
    line(ctx,284,672,796,672,'#315d70',2);
    line(ctx,284,974,796,974,'#315d70',3);
    // Two detailed wall sconces.
    for(const x of [183,897]){
      rr(ctx,x-5,929,10,66,3,'#426473');
      withAlpha(ctx,.7*furnishing,()=>{
        const light=ctx.createRadialGradient(x,927,0,x,927,91);light.addColorStop(0,'#b8d85a88');light.addColorStop(1,'#b8d85a00');ctx.fillStyle=light;ctx.fillRect(x-91,836,182,182);
      });
      rr(ctx,x-16,912,32,28,7,furnishing>.5?P.lime:'#3d6271');
    }
  });

  // Dimension annotations establish the first drawing, then recede.
  withAlpha(ctx,plan*(1-smooth(4.5,6.8,t)),()=>{
    line(ctx,284,609,796,609,P.teal,1.5);
    line(ctx,284,600,284,618,P.teal,2);line(ctx,796,600,796,618,P.teal,2);
    text(ctx,'THE CANVAS',540,593,18,P.lime,'center',600);
    line(ctx,87,754,87,1362,P.teal,1.5);line(ctx,77,754,98,754,P.teal,2);line(ctx,77,1362,98,1362,P.teal,2);
    rr(ctx,389,1080,302,137,8,null,P.teal,2);
    text(ctx,'YOUR VISION',540,1157,24,P.teal,'center',700);
    const penx=mix(140,937,clamp((t-.3)/4.6));
    line(ctx,penx,665,penx,1350,'#b8d85a',1.2);
    circle(ctx,penx,665,4,P.lime);
  });

  // Stage platform emerges directly from the floor footprint.
  const rise=smooth(5.6,7.8,t);
  withAlpha(ctx,rise,()=>{
    const top=999-rise*66;
    path(ctx,[[305,top],[775,top],[820,top+100],[259,top+100]],'#44758a');
    path(ctx,[[259,top+100],[820,top+100],[820,1058],[259,1058]],'#2b5269');
    line(ctx,266,top+99,812,top+99,P.teal,3);
    // Two centered riser steps.
    path(ctx,[[455,1058],[625,1058],[642,1080],[438,1080]],'#365f75');
    path(ctx,[[438,1080],[642,1080],[642,1093],[438,1093]],'#204357');
    path(ctx,[[438,1093],[642,1093],[654,1109],[426,1109]],'#365f75');
    path(ctx,[[426,1109],[654,1109],[654,1120],[426,1120]],'#204357');
  });
  const backdrop=smooth(6.4,8.8,t);
  withAlpha(ctx,backdrop,()=>{
    const bottom=943,top=mix(934,731,backdrop);
    rr(ctx,338,top,404,bottom-top,4,'#246382');
    path(ctx,[[338,top],[353,top-14],[757,top-14],[742,top]],'#67959e');
    path(ctx,[[742,top],[757,top-14],[757,bottom-14],[742,bottom]],'#17465f');
    // Sculptural lateral fins open like a paper stage design.
    for(let i=0;i<3;i++){
      const w=19,hh=132+i*22;const yy=bottom-hh*backdrop;
      path(ctx,[[291+i*18,yy],[291+i*18+w,yy-13],[291+i*18+w,bottom-13],[291+i*18,bottom]],i%2?P.teal:P.blue);
      path(ctx,[[751+i*18,yy],[751+i*18+w,yy+13],[751+i*18+w,bottom],[751+i*18,bottom-13]],i%2?P.teal:P.blue);
    }
    withAlpha(ctx,smooth(8,9.2,t),()=>{
      circle(ctx,540,828,52,P.lime);
      star(ctx,540,828,23,P.navy);
      text(ctx,'TOGETHER',540,912,24,P.ivory,'center',700);
      // A thin border slowly traces across the original backdrop.
      rr(ctx,355,746,370,182,4,null,'#6aa3ae',1.2);
    });
  });
  // Lectern arrives from the right and provides a human scale reference.
  const lect=smooth(9,10.4,t);
  withAlpha(ctx,lect,()=>{
    const x=700+(1-lect)*75;
    path(ctx,[[x-20,905],[x+22,917],[x+14,993],[x-15,983]],P.ivory);
    path(ctx,[[x-23,901],[x+20,901],[x+28,914],[x-18,914]],P.coral);
    line(ctx,x+5,901,x+7,881,P.navy,2);circle(ctx,x+8,880,3,P.navy);
  });

  // Lighting rig and side fixtures arrive before the banquet setting.
  const rig=smooth(10.8,12.2,t);
  withAlpha(ctx,rig,()=>{
    const y=700-(1-rig)*46;
    line(ctx,247,y,833,y,P.teal,7);line(ctx,247,y+19,833,y+19,P.teal,4);
    for(let i=0;i<14;i++)line(ctx,247+i*42,y,268+i*42,y+19,P.teal,2);
    [276,391,540,690,805].forEach((x,i)=>{
      line(ctx,x,y+17,x,y+38,P.teal,3);
      ctx.save();ctx.translate(x,y+43);ctx.rotate((i-2)*.10+Math.sin(t*.4+i)*.03);rr(ctx,-13,-8,26,23,5,'#648e99');rr(ctx,-10,11,20,6,3,P.lime);ctx.restore();
    });
  });

  // Tables are drawn back-to-front; soft shaded tops, individual chairs and florals.
  const tablePositions=[{u:.23,v:.36,r:41},{u:.77,v:.36,r:41},{u:.18,v:.76,r:56},{u:.80,v:.76,r:56}];
  tablePositions.forEach((item,i)=>{
    const entry=smooth(11.7+i*.36,12.9+i*.36,t);
    const p=project(item.u,item.v),x=p.x,y=p.y+(1-entry)*40,r=item.r;
    withAlpha(ctx,entry,()=>{
      // contact shadow
      ctx.fillStyle='#0a2335';ctx.beginPath();ctx.ellipse(x+4,y+10,r+13,r*.45,0,0,TAU);ctx.fill();
      // chairs use short backrests and a seat ellipse, arranged around table.
      for(let k=0;k<6;k++){
        const a=k*TAU/6+.18;const cx=x+Math.cos(a)*(r+16),cy=y+Math.sin(a)*(r*.45+12);
        ctx.save();ctx.translate(cx,cy);ctx.rotate(Math.sin(a)*.18);
        rr(ctx,-11,-13,22,22,6,P.teal);line(ctx,-7,8,-8,23,'#17384a',2);line(ctx,7,8,8,23,'#17384a',2);ctx.restore();
      }
      // linen drape, top edge and glassware details
      ctx.fillStyle='#c9d0c1';ctx.beginPath();ctx.ellipse(x,y+8,r,r*.45,0,0,Math.PI);ctx.lineTo(x-r,y-8);ctx.lineTo(x+r,y-8);ctx.closePath();ctx.fill();
      ctx.fillStyle=P.ivory;ctx.beginPath();ctx.ellipse(x,y-9,r,r*.43,0,0,TAU);ctx.fill();
      for(let k=0;k<5;k++){
        const a=k*TAU/5;const px=x+Math.cos(a)*r*.68,py=y-9+Math.sin(a)*r*.28;
        ctx.strokeStyle='#afc0b9';ctx.lineWidth=1;ctx.beginPath();ctx.ellipse(px,py,7,3,0,0,TAU);ctx.stroke();
        line(ctx,px+10,py-4,px+10,py+2,'#819e9e',1);
      }
      rr(ctx,x-4,y-24,8,17,3,P.coral);
      for(let k=0;k<4;k++){line(ctx,x,y-19,x+(k-1.5)*4,y-32-k%2*6,P.teal,2);circle(ctx,x+(k-1.5)*4,y-32-k%2*6,4,k%2?P.lime:P.coral);}
    });
  });

  // Arrival carpet leaves an unbroken path to the stage.
  withAlpha(ctx,smooth(14.2,15.3,t),()=>{
    path(ctx,[[515,1124],[565,1124],[595,1364],[485,1364]],'#405c62');
    line(ctx,515,1124,485,1364,'#839566',2);line(ctx,565,1124,595,1364,'#839566',2);
  });

  // Final lighting has softly feathered beams rather than opaque triangles.
  withAlpha(ctx,smooth(15.8,17.8,t)*.65,()=>{
    const sway=Math.sin(t*.43)*33;
    [
      {x:276,tip:620+sway,color:'184,216,90'},
      {x:805,tip:470-sway,color:'246,242,233'},
      {x:540,tip:540+sway*.4,color:'81,143,153'}
    ].forEach((b,i)=>{
      const g=ctx.createLinearGradient(b.x,750,b.tip,1305);g.addColorStop(0,`rgba(${b.color},0.01)`);g.addColorStop(.65,`rgba(${b.color},0.13)`);g.addColorStop(1,`rgba(${b.color},0.01)`);
      path(ctx,[[b.x-5,758],[b.x+5,758],[b.tip+98,1300],[b.tip-98,1300]],g);
    });
  });

  // The room becomes inhabited: purposeful arrivals, hosts and small conversations.
  const guests=[
    {u:.13,v:.23,col:P.coral,delay:0,s:.51},{u:.81,v:.24,col:P.ivory,delay:.3,s:.51},
    {u:.40,v:.51,col:P.blue,delay:.2,s:.62},{u:.62,v:.56,col:P.coral,delay:.4,s:.66},
    {u:.27,v:.83,col:P.ivory,delay:.5,s:.76},{u:.72,v:.87,col:P.blue,delay:.7,s:.78},
    {u:.47,v:.92,col:P.coral,delay:.9,s:.81},{u:.54,v:.99,col:P.teal,delay:1.2,s:.85}
  ];
  guests.forEach((g,i)=>{
    const arrival=smooth(16.4+g.delay,18.8+g.delay,t);if(arrival<=0)return;
    const target=project(g.u,g.v),from=project(i%2?.99:.01,Math.min(1,g.v+.18));
    const x=mix(from.x,target.x,arrival),y=mix(from.y,target.y,arrival);
    withAlpha(ctx,arrival,()=>person(ctx,x,y,g.s,g.col));
  });
  withAlpha(ctx,smooth(17.5,18.7,t),()=>{
    person(ctx,668,985,.64,P.coral);
    // Audience members near the back of the room finish the sense of scale.
    person(ctx,401,1007,.51,P.ivory);person(ctx,447,1013,.53,P.blue);
  });

  // Four understated editorial phase markers.
  const words=['VISION','SETTING','DETAILS','EXPERIENCE'];
  for(let i=0;i<4;i++){
    const x=88+i*229;
    rr(ctx,x,1590,202,3,2,'#26485d');
    const p=clamp((t-starts[i])/5.5);if(p>0)rr(ctx,x,1590,202*p,3,2,P.lime);
    text(ctx,words[i],x,1626,24,i<=h?P.lime:P.muted,'left',600);
  }
}

function mixColor(a,b,p){
  const av=parseInt(a.slice(1),16),bv=parseInt(b.slice(1),16),out=[];
  for(const shift of [16,8,0])out.push(Math.round(((av>>shift)&255)*(1-p)+((bv>>shift)&255)*p).toString(16).padStart(2,'0'));
  return '#'+out.join('');
}

module.exports={title,subtitle,draw,storyboard};
