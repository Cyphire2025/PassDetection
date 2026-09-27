'use strict';

// Original geometric animation. All times refer to the 26 second master.
const title = 'Great Work Deserves Great Journeys';
const subtitle = 'Incentive travel, with a sense of occasion.';
const storyboard = [
  { time: '0–5.5', scene: 'A sculpted trophy rises from an architectural plinth; reward ribbons unfurl.' },
  { time: '5.5–11', scene: 'The trophy becomes a boarding pass as an aircraft draws a route through an illustrated world.' },
  { time: '11–16.5', scene: 'The route arrives at an original island retreat with a sun, palms, waves and a team gathering.' },
  { time: '16.5–22', scene: 'The setting transforms into an awards evening, complete with a stage, light beams and applause.' },
  { time: '22–26', scene: 'Shared Global Connect Travels logo and enquiry end card.' }
];

function draw(ctx, t, C) {
  const { P, clamp, mix, ease, smooth, text, lines, rr, line, circle, path, withAlpha, plane, person, star } = C;
  const out = (a,b) => 1-smooth(a,b,t);
  const fade = (a,b,c,d) => smooth(a,b,t)*out(c,d);
  const TAU=Math.PI*2;
  ctx.fillStyle=P.navy; ctx.fillRect(0,0,1080,1920);

  // Quiet print-like linework adds depth without competing with the lettering.
  withAlpha(ctx,.12,()=>{
    for(let i=0;i<9;i++){
      ctx.beginPath(); ctx.strokeStyle=i%3===0?P.teal:P.blue;ctx.lineWidth=1.5;
      ctx.ellipse(1010,1020,240+i*55,430+i*66,-.25,0,TAU);ctx.stroke();
    }
  });
  const h=t<5.5?0:t<11?1:t<16.5?2:3;
  const headings=[['Great work.','Greater journeys.'],['Turn recognition','into a destination.'],['Room to reconnect.','Time to explore.'],['A shared journey.','A lasting memory.']];
  const kickers=['INCENTIVE TRAVEL','REWARD THE PEOPLE BEHIND THE PROGRESS','BEYOND THE EVERYDAY','CELEBRATE TOGETHER'];
  const starts=[0,5.5,11,16.5];
  const captions=[['Give achievement a new horizon.','Create something to look forward to.'],['The reward starts with anticipation.','Let the next chapter take flight.'],['New surroundings. Shared experiences.','Bring your team closer together.'],['From the first welcome to the final applause.','Make every moment feel considered.']];
  let tx=smooth(starts[h],starts[h]+.65,t);
  withAlpha(ctx,tx,()=>{
    text(ctx,kickers[h],88,285,24,P.lime,'left',700);
    lines(ctx,headings[h],84,378,68,81,P.ivory,'left',700);
    text(ctx,captions[h][0],88,1470,36,P.ivory,'left',500);
    text(ctx,captions[h][1],88,1520,34,P.muted,'left',400);
  });

  // A restrained progress rule ties the four transformations together.
  for(let i=0;i<4;i++){
    rr(ctx,88+i*229,1588,202,3,2,'#254459');
    const progress=clamp((t-starts[i])/5.5);
    if(progress>0) rr(ctx,88+i*229,1588,202*progress,3,2,P.lime);
  }

  const trophyAlpha=out(5.15,6.15);
  withAlpha(ctx,trophyAlpha,()=>{
    const rise=ease(clamp(t/1.2));
    const lift=(1-rise)*160;
    ctx.save();ctx.translate(0,lift);
    // Radiating award halo, rotating slowly behind the cup.
    withAlpha(ctx,.40*rise,()=>{
      for(let i=0;i<18;i++){
        const a=i*TAU/18+t*.025;
        line(ctx,540+Math.cos(a)*257,944+Math.sin(a)*257,540+Math.cos(a)*283,944+Math.sin(a)*283,P.teal,2);
      }
      circle(ctx,540,944,233,null,P.teal,1.5);
    });
    // Plinth uses three faces, maintaining a tangible physical object.
    path(ctx,[[277,1244],[704,1244],[806,1292],[379,1292]],P.teal);
    path(ctx,[[277,1244],[379,1292],[379,1350],[277,1300]],'#235369');
    path(ctx,[[379,1292],[806,1292],[806,1350],[379,1350]],'#396b7b');
    line(ctx,295,1251,700,1251,'#86b3b5',2);
    // Trophy handles are nested open arcs rather than a pictogram.
    ctx.strokeStyle=P.lime;ctx.lineWidth=20;
    ctx.beginPath();ctx.moveTo(399,818);ctx.bezierCurveTo(292,781,316,999,437,981);ctx.stroke();
    ctx.beginPath();ctx.moveTo(681,818);ctx.bezierCurveTo(788,781,764,999,643,981);ctx.stroke();
    const gold=ctx.createLinearGradient(396,0,684,0);gold.addColorStop(0,'#7eae47');gold.addColorStop(.34,'#d6e897');gold.addColorStop(.63,P.lime);gold.addColorStop(1,'#759c43');
    ctx.fillStyle=gold;ctx.beginPath();ctx.moveTo(396,784);ctx.lineTo(684,784);ctx.bezierCurveTo(678,935,648,1027,561,1054);ctx.lineTo(561,1150);ctx.lineTo(633,1177);ctx.lineTo(633,1208);ctx.lineTo(447,1208);ctx.lineTo(447,1177);ctx.lineTo(519,1150);ctx.lineTo(519,1054);ctx.bezierCurveTo(433,1027,402,935,396,784);ctx.closePath();ctx.fill();
    ctx.fillStyle='#dfedb2';ctx.beginPath();ctx.ellipse(540,784,145,21,0,0,TAU);ctx.fill();
    ctx.fillStyle='#87ac4f';ctx.beginPath();ctx.ellipse(540,784,119,10,0,0,TAU);ctx.fill();
    star(ctx,540,918,45,P.navy);
    line(ctx,465,1193,615,1193,'#e0ecb8',3);
    // Two free ribbons remain in continual gentle movement.
    for(let side=-1;side<=1;side+=2){
      const sx=540+side*170;
      ctx.beginPath();ctx.moveTo(sx,1000);ctx.bezierCurveTo(sx+side*95,1032,sx+side*(85+Math.sin(t)*15),1150,sx+side*168,1192);
      ctx.strokeStyle=side<0?P.coral:P.blue;ctx.lineWidth=20;ctx.stroke();
      ctx.beginPath();ctx.moveTo(sx,1000);ctx.bezierCurveTo(sx+side*95,1032,sx+side*(85+Math.sin(t)*15),1150,sx+side*168,1192);ctx.strokeStyle=P.ivory;ctx.lineWidth=1;ctx.stroke();
    }
    for(let i=0;i<8;i++){
      const a=i*2.4; const x=250+(i*127)%600; const y=718+(i*83)%490+Math.sin(t*1.4+a)*14;
      if(i%2)star(ctx,x,y,7,P.lime);else {ctx.save();ctx.translate(x,y);ctx.rotate(t*.3+a);ctx.fillStyle=P.coral;ctx.fillRect(-3,-10,6,20);ctx.restore();}
    }
    ctx.restore();
  });

  withAlpha(ctx,fade(5.0,6.05,10.8,11.7),()=>{
    const q=ease(clamp((t-5.1)/1.0));
    // Circular atlas is hand-drawn, with simplified original landforms.
    const gx=540,gy=935;
    circle(ctx,gx,gy,315,'#103047',P.teal,2);
    ctx.save();ctx.beginPath();ctx.arc(gx,gy,313,0,TAU);ctx.clip();
    withAlpha(ctx,.4,()=>{
      for(let j=-2;j<=2;j++) {ctx.beginPath();ctx.strokeStyle=P.teal;ctx.lineWidth=1;ctx.ellipse(gx,gy,95+Math.abs(j)*75,313,0,0,TAU);ctx.stroke();line(ctx,220,gy+j*94,860,gy+j*94,P.teal,1);}
    });
    path(ctx,[[271,770],[369,698],[439,729],[459,786],[435,835],[475,866],[437,928],[383,929],[359,999],[321,952],[307,867]],'#315e6b');
    path(ctx,[[515,865],[563,817],[617,833],[646,882],[696,891],[722,942],[686,968],[650,948],[624,1003],[579,1023],[564,971],[537,951]],'#315e6b');
    path(ctx,[[751,1089],[801,1062],[839,1090],[818,1130],[766,1138]],'#315e6b');
    // Route progressively traces with an aircraft at its head.
    const routeP=clamp((t-6.15)/3.2);
    ctx.strokeStyle=P.lime;ctx.lineWidth=3;ctx.setLineDash([8,10]);ctx.beginPath();
    for(let k=0;k<=80*routeP;k++){
      const p=k/80;const x=300+455*p;const y=982-170*Math.sin(p*Math.PI)-70*p;k===0?ctx.moveTo(x,y):ctx.lineTo(x,y);
    }ctx.stroke();ctx.setLineDash([]);
    const px=300+455*routeP,py=982-170*Math.sin(routeP*Math.PI)-70*routeP;
    const angle=Math.atan2(-170*Math.PI*Math.cos(routeP*Math.PI)-70,455);
    plane(ctx,px,py,.72,angle+Math.PI/2,P.ivory);
    circle(ctx,300,982,7,P.lime);circle(ctx,755,912,7,P.lime);
    ctx.restore();
    // Boarding pass slides out of the trophy's location, then tilts into travel.
    ctx.save();ctx.translate(540,1215+(1-q)*120);ctx.rotate(-.055+Math.sin(t*.45)*.01);
    rr(ctx,-335,-100,670,200,20,P.ivory);
    rr(ctx,-335,-100,24,200,12,P.lime);
    line(ctx,171,-78,171,78,'#bcc8c6',2);
    circle(ctx,171,-100,13,P.navy);circle(ctx,171,100,13,P.navy);
    text(ctx,'YOUR NEXT CHAPTER',-276,-39,19,P.teal,'left',700);
    text(ctx,'WELL EARNED.',-276,15,38,P.navy,'left',700);
    text(ctx,'INCENTIVE JOURNEY',-276,58,17,P.navy,'left',500);
    plane(ctx,243,-29,.44,0,P.navy);
    for(let i=0;i<20;i++) {ctx.fillStyle=P.navy;ctx.fillRect(205+i*4,23,i%3===0?3:1,32);}
    ctx.restore();
  });

  withAlpha(ctx,fade(10.85,11.7,16.3,17.15),()=>{
    const q=ease(clamp((t-11)/1.25));
    // Island archipelago; every wave and palm is made for this film.
    const sea=ctx.createLinearGradient(0,700,0,1365);sea.addColorStop(0,'#153d55');sea.addColorStop(1,'#256c80');
    rr(ctx,116,672,848,682,190,sea);
    circle(ctx,746,808,89,P.lime);
    for(let i=0;i<8;i++){
      const yy=934+i*52;
      ctx.beginPath();ctx.strokeStyle=i%2?'#5b9a9f':'#3a8091';ctx.lineWidth=3;
      for(let x=156;x<=926;x+=12){const y=yy+Math.sin(x/77+t*.85+i)*5;x===156?ctx.moveTo(x,y):ctx.lineTo(x,y);}ctx.stroke();
    }
    ctx.save();ctx.translate(0,(1-q)*170);
    path(ctx,[[226,1168],[306,1098],[422,1076],[486,1008],[608,1022],[701,1092],[844,1144],[891,1204],[801,1260],[665,1287],[494,1274],[341,1241]],'#739c70');
    path(ctx,[[214,1186],[303,1122],[418,1104],[490,1051],[602,1061],[703,1124],[842,1172],[877,1213],[786,1250],[650,1270],[495,1251],[331,1221]],'#e9d8b5');
    path(ctx,[[298,1189],[399,1138],[510,1117],[619,1134],[725,1192],[648,1230],[503,1235],[387,1214]],'#92b69a');
    // Boutique meeting pavilion.
    path(ctx,[[401,1103],[556,1051],[701,1103],[548,1154]],P.coral);
    path(ctx,[[416,1110],[548,1154],[548,1230],[416,1186]],'#e0c8a5');
    path(ctx,[[548,1154],[686,1109],[686,1181],[548,1230]],'#baa98d');
    for(let i=0;i<3;i++)path(ctx,[[568+i*36,1164-i*12],[593+i*36,1156-i*12],[593+i*36,1192-i*12],[568+i*36,1200-i*12]],P.navy);
    path(ctx,[[451,1140],[504,1158],[504,1205],[451,1188]],P.navy);
    line(ctx,551,1157,551,1231,P.ivory,4);
    // Palms use curved trunks and alternating fronds.
    const palm=(x,y,s,lean)=>{
      ctx.save();ctx.translate(x,y);ctx.scale(s,s);
      ctx.beginPath();ctx.moveTo(0,0);ctx.quadraticCurveTo(lean,-72,lean+3,-153);ctx.strokeStyle='#b79673';ctx.lineWidth=12;ctx.stroke();
      for(let k=-3;k<=3;k++){
        const a=-Math.PI/2+k*.41;const xx=lean+3+Math.cos(a)*93,yy=-153+Math.sin(a)*51+37;
        ctx.beginPath();ctx.moveTo(lean+3,-153);ctx.quadraticCurveTo((xx+lean)/2,-188,xx,yy);ctx.strokeStyle=k%2?P.lime:'#77a757';ctx.lineWidth=14;ctx.stroke();
      }ctx.restore();
    };
    palm(315,1140,1.1,22);palm(788,1170,.95,-18);
    // Team silhouettes gather along the shore rather than as repeated icons.
    const team=[[-84,0,P.blue],[-39,9,P.coral],[4,0,P.navy],[48,8,P.teal],[88,-2,P.blue]];
    team.forEach((v,i)=>{const enter=smooth(12.4+i*.18,13.45+i*.18,t);withAlpha(ctx,enter,()=>person(ctx,532+v[0],1290+v[1]+(1-enter)*35,.68,v[2]));});
    ctx.restore();
    // Seabirds and a little yacht continue moving after the arrival.
    for(let i=0;i<3;i++){
      const bx=317+i*67+Math.sin(t*.3)*8,by=797+i%2*32;
      ctx.beginPath();ctx.strokeStyle=P.ivory;ctx.lineWidth=3;ctx.moveTo(bx-14,by+4);ctx.quadraticCurveTo(bx-5,by-7,bx,by);ctx.quadraticCurveTo(bx+8,by-7,bx+18,by+4);ctx.stroke();
    }
    const boatx=812-Math.sin(t*.28)*22;
    path(ctx,[[boatx-30,992],[boatx+36,992],[boatx+21,1006],[boatx-17,1006]],P.ivory);
    path(ctx,[[boatx-2,985],[boatx-2,929],[boatx+26,985]],P.lime);line(ctx,boatx-5,927,boatx-5,995,P.ivory,2);
  });

  withAlpha(ctx,fade(16.35,17.2,22.2,22.8),()=>{
    const q=smooth(16.6,17.7,t);
    // A circular sun becomes the awards-stage medallion.
    const medx=mix(746,540,q),medy=mix(808,928,q);
    const stageY=1188+(1-q)*90;
    path(ctx,[[190,stageY],[775,stageY],[904,stageY+85],[320,stageY+85]],'#335a70');
    path(ctx,[[320,stageY+85],[904,stageY+85],[904,stageY+119],[320,stageY+119]],'#1d425a');
    path(ctx,[[190,stageY],[320,stageY+85],[320,stageY+119],[190,stageY+34]],'#102b42');
    rr(ctx,242,721,596,468,22,'#15415d');
    rr(ctx,262,741,556,427,14,'#11334b',P.teal,2);
    for(let j=0;j<13;j++)line(ctx,279+j*43,753,279+j*43,1156,j%2?'#1c4860':'#174058',2);
    circle(ctx,medx,medy,mix(89,108,q),P.lime);
    star(ctx,medx,medy,47,P.navy);
    text(ctx,'A MOMENT TO CELEBRATE',540,1090,22,P.ivory,'center',700);
    // Stage luminaires sweep very gently so the finished composition stays alive.
    withAlpha(ctx,.17,()=>{
      path(ctx,[[245,692],[330+Math.sin(t*.7)*25,1180],[550,1180]],P.lime);
      path(ctx,[[832,692],[520,1180],[760+Math.cos(t*.7)*25,1180]],P.ivory);
    });
    [245,832].forEach(x=>{rr(ctx,x-24,675,48,31,8,P.teal);circle(ctx,x,706,9,P.ivory);});
    // Team on stage, each arrives independently.
    const pp=[[-201,P.coral],[-122,P.blue],[-40,P.ivory],[44,P.coral],[125,P.teal],[205,P.blue]];
    pp.forEach((p,i)=>{const arrival=smooth(17.3+i*.12,18.3+i*.12,t);withAlpha(ctx,arrival,()=>person(ctx,540+p[0],1210+(1-arrival)*55,.92,p[1]));});
    // Foreground audience and restrained celebratory confetti.
    withAlpha(ctx,q,()=>{
      for(let i=0;i<9;i++){const x=195+i*86;circle(ctx,x,1356+(i%2)*8,15,'#315568');rr(ctx,x-24,1374+(i%2)*8,48,49,17,'#315568');}
      for(let i=0;i<23;i++){
        const xx=185+(i*107)%715;const yy=684+((t*41+i*83)%545);
        ctx.save();ctx.translate(xx,yy);ctx.rotate(t+i*1.2);ctx.fillStyle=[P.lime,P.coral,P.ivory][i%3];ctx.fillRect(-3,-7,6,14);ctx.restore();
      }
    });
  });
}

module.exports={title,subtitle,draw,storyboard};
