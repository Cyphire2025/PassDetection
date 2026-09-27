/* Original vector motion design. All scenery is drawn procedurally. */
'use strict';

const title = 'Many Cities. One Experience.';
const subtitle = 'Different departure cities. One shared experience.';
const storyboard = [
  { time: '00–05.5', scene: 'Three miniature departure terminals appear on an illustrative route diagram; ribbons extend towards one shared destination.', copy: 'Many cities. One experience.' },
  { time: '05.5–11', scene: 'Aircraft follow curved routes into a destination hub, drawing luminous trails behind them.', copy: 'Different departures. A shared destination.' },
  { time: '11–16.5', scene: 'A dimensional hotel rises behind a curved road; animated coaches arrive and guests enter through a welcoming reception.', copy: 'Every arrival. A warm welcome.' },
  { time: '16.5–22', scene: 'The roof lifts into an open gala scene with spotlights, guests, tables and an animated stage.', copy: 'Together. For the big moment.' },
  { time: '22–26', scene: 'Shared branded closing card supplied by renderer.' }
];

function draw(ctx, t, C) {
  const { P, clamp, ease, smooth, text, lines, rr, line, circle, path, plane, person, withAlpha } = C;
  const PI = Math.PI;
  const q = n => clamp(n);
  const E = n => ease(q(n));
  const fade = (start, end) => smooth(start, start + 0.55, t) * (1 - smooth(end - 0.5, end, t));
  const f = (a, b, u) => a + (b - a) * u;
  const curve = (a,b,c,d,u) => ({x:Math.pow(1-u,3)*a.x+3*Math.pow(1-u,2)*u*b.x+3*(1-u)*u*u*c.x+u*u*u*d.x,y:Math.pow(1-u,3)*a.y+3*Math.pow(1-u,2)*u*b.y+3*(1-u)*u*u*c.y+u*u*u*d.y});
  const curves = [
    [{x:235,y:788},{x:585,y:675},{x:820,y:812},{x:776,y:1030}],
    [{x:215,y:1105},{x:438,y:1060},{x:580,y:828},{x:776,y:1030}],
    [{x:485,y:1280},{x:518,y:1090},{x:624,y:1220},{x:776,y:1030}]
  ];
  function route(points, progress, color, width = 4) {
    ctx.beginPath();
    for(let i=0;i<=80;i++){const r=curve(...points,progress*i/80);i?ctx.lineTo(r.x,r.y):ctx.moveTo(r.x,r.y);}
    ctx.strokeStyle=color;ctx.lineWidth=width;ctx.lineCap='round';ctx.stroke();
  }
  function terminal(x,y,s,label,delay) {
    const v=E((t-delay)/0.85);
    ctx.save();ctx.translate(x,y+55*(1-v));ctx.scale(s*v,s*v);ctx.globalAlpha*=v;
    path(ctx,[[-105,34],[58,34],[106,70],[-55,70]],'#061522');
    rr(ctx,-102,-8,162,57,8,P.ivory);
    path(ctx,[[60,-8],[102,16],[102,72],[60,49]],'#b2c3c5');
    path(ctx,[[-102,-8],[60,-8],[102,16],[-60,16]],'#dae2df');
    rr(ctx,-86,18,128,17,3,P.blue);
    for(let z=0;z<5;z++)line(ctx,-76+z*27,19,-76+z*27,34,'#cbe9f1',3);
    rr(ctx,12,-48,15,44,3,P.ivory);rr(ctx,-3,-58,46,21,5,P.teal);
    line(ctx,21,-68,21,-58,P.lime,3);circle(ctx,21,-72,4,P.lime);
    ctx.restore();
    withAlpha(ctx,v,()=>{rr(ctx,x-85,y+82,170,48,24,'#17394b');text(ctx,label,x,y+114,28,P.ivory,'center',600);});
  }
  function smallPlane(points,u,color,size=1) {
    const pos=curve(...points,u), next=curve(...points,Math.min(1,u+0.003)), prev=curve(...points,Math.max(0,u-0.003));
    plane(ctx,pos.x,pos.y,size,Math.atan2(next.y-prev.y,next.x-prev.x)+PI/2,color);
  }
  function road(y) {
    ctx.save();
    ctx.beginPath();ctx.moveTo(70,y+135);ctx.bezierCurveTo(330,y-70,600,y+220,1010,y+25);ctx.strokeStyle='#263f4d';ctx.lineWidth=116;ctx.lineCap='round';ctx.stroke();
    ctx.strokeStyle='#59727a';ctx.lineWidth=3;ctx.setLineDash([21,24]);ctx.lineDashOffset=-t*38;ctx.stroke();ctx.setLineDash([]);
    ctx.restore();
  }
  function coach(x,y,s,color) {
    ctx.save();ctx.translate(x,y);ctx.scale(s,s);
    ctx.globalAlpha*=.26;ctx.beginPath();ctx.ellipse(6,59,130,22,0,0,PI*2);ctx.fillStyle='#021019';ctx.fill();ctx.globalAlpha/=.26;
    rr(ctx,-125,-44,250,104,18,color);
    path(ctx,[[-110,-44],[100,-44],[126,-25],[-85,-25]],'#d6e4dd');
    rr(ctx,-110,-24,175,44,8,'#164458');rr(ctx,73,-24,40,57,8,'#164458');
    for(let k=0;k<5;k++)line(ctx,-84+k*32,-22,-84+k*32,18,'#78a5b3',3);
    rr(ctx,-111,29,127,6,3,P.lime);rr(ctx,103,32,14,10,3,'#fff3c5');
    [-77,76].forEach(xx=>{circle(ctx,xx,57,21,'#071722');circle(ctx,xx,57,11,'#8b9fa4');circle(ctx,xx,57,4,P.ivory);});
    text(ctx,'GLOBAL CONNECT',-107,48,10,P.navy,'left',800);
    ctx.restore();
  }
  function palm(x,y,s,lean=1) {
    ctx.save();ctx.translate(x,y);ctx.scale(s,s);
    ctx.beginPath();ctx.moveTo(0,0);ctx.quadraticCurveTo(lean*15,-70,lean*2,-135);ctx.strokeStyle='#a68368';ctx.lineWidth=12;ctx.lineCap='round';ctx.stroke();
    const wave=Math.sin(t*1.4+x)*.07;
    for(let k=0;k<6;k++){ctx.save();ctx.translate(lean*2,-135);ctx.rotate(k*PI/3+wave);path(ctx,[[0,0],[35,-25],[77,2],[35,-8]],k%2?P.teal:'#80aa87');ctx.restore();}
    ctx.restore();
  }
  function hotel(u) {
    const rise=E(u);
    ctx.save();ctx.translate(540,1130+130*(1-rise));ctx.globalAlpha*=rise;
    path(ctx,[[-327,24],[229,24],[354,101],[-225,101]],'#092331');
    path(ctx,[[-272,-273],[212,-273],[305,-212],[-179,-212]],'#e4e0d2');
    path(ctx,[[212,-273],[305,-212],[305,30],[212,-32]],'#829d9c');
    rr(ctx,-272,-273,484,270,8,P.ivory);
    path(ctx,[[-294,-286],[213,-286],[333,-215],[305,-199],[205,-256],[-294,-256]],P.teal);
    for(let r=0;r<3;r++)for(let c=0;c<8;c++){
      const lit=(c+r)%3===0 || u>.7;
      rr(ctx,-246+c*56,-228+r*67,34,42,3,lit?'#dfc995':'#487284');
      line(ctx,-229+c*56,-227+r*67,-229+c*56,-187+r*67,'#cdd9d3',2);
    }
    for(let r=0;r<3;r++)for(let c=0;c<2;c++)path(ctx,[[231+c*36,-223+r*67],[253+c*36,-209+r*67],[253+c*36,-171+r*67],[231+c*36,-185+r*67]],'#476978');
    rr(ctx,-59,-93,113,97,4,'#123849');line(ctx,-3,-90,-3,1,'#8dadb1',3);
    path(ctx,[[-97,-96],[55,-96],[111,-56],[-41,-56]],P.lime);
    line(ctx,-66,-74,-66,30,'#dce5da',5);line(ctx,79,-56,79,49,'#dce5da',5);
    rr(ctx,-157,-340,270,39,19,'#14394a');text(ctx,'A WARM WELCOME',-22,-314,19,P.ivory,'center',700);
    for(let j=0;j<5;j++) {const phase=(t*.34+j*.17)%1;person(ctx,-123+phase*80,34-phase*55,.47,j%2?P.coral:P.blue);}
    ctx.restore();
    palm(190,1163,0.95,-1);palm(900,1195,1.04,1);
  }
  function gala(local) {
    const build=E(local/.8);
    ctx.save();ctx.translate(540,1060);
    ctx.scale(.92+.08*build,.92+.08*build);ctx.globalAlpha*=build;
    const light=ctx.createRadialGradient(0,-140,10,0,-100,390);light.addColorStop(0,'#204754');light.addColorStop(1,'#0b2131');
    rr(ctx,-410,-338,820,660,35,light);
    path(ctx,[[-410,120],[410,120],[350,340],[-350,340]],'#173945');
    for(let i=0;i<7;i++){const xx=-355+i*118;line(ctx,xx,-294,xx,-66,'#38505a',2);}
    rr(ctx,-315,-261,630,239,18,'#0b2535',P.teal,2);
    const barY=-209;for(let i=0;i<7;i++){const h=16+Math.sin(t*2+i*.8)*10;rr(ctx,-139+i*43,barY-h/2,12,h,6,i%2?P.teal:P.lime);}
    text(ctx,'ONE SHARED',0,-123,34,P.ivory,'center',700);
    text(ctx,'EXPERIENCE',0,-75,46,P.lime,'center',800);
    path(ctx,[[-347,-3],[283,-3],[362,44],[-271,44]],'#567581');
    path(ctx,[[-271,44],[362,44],[362,69],[-271,69]],'#304f5c');
    path(ctx,[[-347,-3],[-271,44],[-271,69],[-347,22]],'#3d6570');
    [-310,310].forEach((xx,i)=>{
      circle(ctx,xx,-299,14,P.lime);
      const sway=Math.sin(t*.6+i)*55;
      const beam=ctx.createLinearGradient(xx,-295,xx+sway,50);beam.addColorStop(0,'#d3e99755');beam.addColorStop(1,'#d3e99700');
      path(ctx,[[xx-6,-290],[xx+6,-290],[xx+sway+180,137],[xx+sway-120,137]],beam);
    });
    [-228,210].forEach((xx,idx)=>{
      ctx.beginPath();ctx.ellipse(xx,160+idx*60,118,53,0,0,2*PI);ctx.fillStyle='#c7d2c0';ctx.fill();
      ctx.beginPath();ctx.ellipse(xx,150+idx*60,118,49,0,0,2*PI);ctx.fillStyle=P.ivory;ctx.fill();
      circle(ctx,xx,150+idx*60,15,P.teal);for(let s=0;s<6;s++){const a=s*PI/3;circle(ctx,xx+Math.cos(a)*86,150+idx*60+Math.sin(a)*33,9,'#d4c1a0');}
      [-1,1].forEach((n,j)=>person(ctx,xx+n*108,184+idx*60,.6,j?P.coral:P.blue));
    });
    person(ctx,32,14,.7,P.coral);person(ctx,-19,0,.64,P.blue);
    for(let i=0;i<32;i++){
      const xx=-350+((i*163)%710), yy=-350+((local*56+i*79)%580);
      ctx.save();ctx.translate(xx+Math.sin(local+i)*13,yy);ctx.rotate(local*.8+i);ctx.fillStyle=[P.lime,P.ivory,P.coral][i%3];ctx.fillRect(-3,-8,6,16);ctx.restore();
    }
    ctx.restore();
  }

  // Slowly moving atmospheric backdrop and an editorial route motif.
  ctx.fillStyle=P.navy;ctx.fillRect(0,0,1080,1920);
  const bg=ctx.createRadialGradient(680,980,80,600,900,1120);bg.addColorStop(0,'#17394a');bg.addColorStop(1,P.navy);ctx.fillStyle=bg;ctx.fillRect(0,190,1080,1510);
  withAlpha(ctx,.16,()=>{for(let i=0;i<20;i++){const yy=640+i*42;line(ctx,90,yy,990,yy,'#718b91',1);}for(let i=0;i<17;i++)line(ctx,90+i*56,600,90+i*56,1435,'#718b91',1);});
  for(let i=0;i<18;i++){const xx=100+(i*157)%885, yy=670+(i*89)%680;circle(ctx,xx,yy+Math.sin(t*.45+i)*7,1.5,'#729697');}

  const scenes=[
    {s:0,e:5.65,headline:['Many cities.','One experience.'],tag:'THE GROUP JOURNEY',caption:'Different departure cities. One shared experience.'},
    {s:5.1,e:11.15,headline:['Different departures.','A shared destination.'],tag:'CONNECTED ARRIVALS',caption:'The journey brings everyone together.'},
    {s:10.6,e:16.65,headline:['Every arrival.','A warm welcome.'],tag:'FROM ARRIVAL TO CHECK-IN',caption:'Transfers. Welcome. A place to settle in.'},
    {s:16.1,e:22.25,headline:['Together.','For the big moment.'],tag:'ONE MEMORABLE OCCASION',caption:'Together, from departure to celebration.'}
  ];
  scenes.forEach((scene,i)=>{
    const a=i===0?1-smooth(5.1,5.65,t):fade(scene.s,scene.e);
    if(a<.001)return;
    withAlpha(ctx,a,()=>{
      const enter=E((t-scene.s)/.7);
      text(ctx,scene.tag,90,278+20*(1-enter),26,P.lime,'left',700);
      lines(ctx,scene.headline,86,374+24*(1-enter),i===1?67:81,i===1?83:95,P.ivory,'left',700);
      text(ctx,scene.caption,540,1502,34,'#cbd8d8','center',500);
      if(i<2){
        ctx.save();const zoom=i===1?1+.055*smooth(5.4,10.8,t):1;ctx.translate(540,1000);ctx.scale(zoom,zoom);ctx.translate(-540,-1000);
        const hubPulse=1+Math.sin(t*2)*.04;
        circle(ctx,776,1030,100*hubPulse,'#bdd95a10','#aac64f30',2);
        circle(ctx,776,1030,69,'#26464a',P.lime,2);
        path(ctx,[[747,1028],[776,994],[805,1028],[805,1056],[747,1056]],P.ivory);
        rr(ctx,770,1031,13,25,2,P.blue);
        circle(ctx,792,1015,4,P.lime);
        text(ctx,'TOGETHER',776,1141,28,P.lime,'center',700);
        curves.forEach((points,k)=>{
          route(points,1,'#355561',3);
          const pr=i===0?E((t-.7-k*.2)/3.9):1;
          route(points,pr,[P.lime,P.blue,P.coral][k],4);
          if(i===1){const u=E((t-5.35-k*.48)/3.7);route(points,u,'#e3efd2',6);if(u<.995)smallPlane(points,u,P.ivory,.68);else{const r=13+Math.sin((t-8.8)*3+k)*6;circle(ctx,776,1030,r,null,[P.lime,P.blue,P.coral][k],2);}}
        });
        terminal(235,760,.72,'DELHI',.3);terminal(215,1080,.69,'MUMBAI',.65);terminal(485,1250,.67,'CHENNAI',1);
        ctx.restore();
      }
      if(i===2){
        const l=t-10.8;
        road(1210);hotel(l/.9);
        const arrival=E((l-.2)/3.3);
        coach(f(-190,580,arrival),1354+Math.sin(arrival*PI)*-40,.83,P.ivory);
        const arrival2=E((l-1)/3.5);
        coach(f(-510,215,arrival2),1335+Math.sin(arrival2*PI)*-20,.53,P.coral);
      }
      if(i===3)gala(t-16.15);
    });
  });
}

module.exports={title,subtitle,draw,storyboard};
