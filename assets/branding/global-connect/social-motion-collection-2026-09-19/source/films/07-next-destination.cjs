/* Original miniature destinations. No stock imagery, map data or footage. */
'use strict';

const title='Where Should Your Team Go Next?';
const subtitle='Reconnect. Exchange ideas. Explore together.';
const storyboard=[
  {time:'00–05.5',scene:'A rotating illustrated compass becomes an ocean globe, which opens into a miniature beach retreat with moving surf and palms.',copy:'Space to reconnect.'},
  {time:'05.5–11',scene:'The island rotates into an illuminated city miniature; buildings assemble around a conference venue as a tram passes.',copy:'A place for big ideas.'},
  {time:'11–16.5',scene:'The skyline becomes dimensional mountain ridges, a winding trail and a small team walking towards a sunrise.',copy:'Room to explore.'},
  {time:'16.5–22',scene:'The three original miniatures orbit into a triangular destination selector, connected by the animated compass.',copy:'Where will your team go next?'},
  {time:'22–26',scene:'Shared branded closing card supplied by renderer.'}
];

function draw(ctx,t,C){
  const {P,clamp,ease,smooth,text,lines,rr,line,circle,path,withAlpha,person}=C;
  const PI=Math.PI;
  const E=v=>ease(clamp(v));
  const lerp=(a,b,p)=>a+(b-a)*p;
  const fade=(start,end)=>smooth(start,start+.65,t)*(1-smooth(end-.6,end,t));
  function ellipse(x,y,rx,ry,color,stroke=null,lw=2){ctx.beginPath();ctx.ellipse(x,y,rx,ry,0,0,PI*2);if(color){ctx.fillStyle=color;ctx.fill();}if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=lw;ctx.stroke();}}
  function base(x,y,w,depth,top,side){
    ellipse(x,y+depth,w,w*.27,side);
    ctx.fillStyle=side;ctx.fillRect(x-w,y,w*2,depth);
    ellipse(x,y,w,w*.27,top);
    ctx.save();ctx.globalAlpha*=.35;ellipse(x,y+depth+30,w*.91,w*.2,'#020d15');ctx.restore();
  }
  function cloud(x,y,s){ctx.save();ctx.translate(x,y);ctx.scale(s,s);ellipse(0,0,51,18,'#cfdee0');ellipse(-22,-8,25,20,'#eaf0e9');ellipse(13,-16,32,27,'#eaf0e9');ellipse(40,-3,26,16,'#eaf0e9');ctx.restore();}
  function palm(x,y,s,phase=0){
    ctx.save();ctx.translate(x,y);ctx.scale(s,s);
    ctx.beginPath();ctx.moveTo(0,0);ctx.bezierCurveTo(11,-44,14,-85,3,-130);ctx.strokeStyle='#b88d5b';ctx.lineWidth=12;ctx.lineCap='round';ctx.stroke();
    for(let i=0;i<5;i++){
      ctx.save();ctx.translate(3,-130);ctx.rotate(i*PI*.39+.3+Math.sin(t*1.1+phase)*.06);
      ctx.beginPath();ctx.moveTo(0,0);ctx.quadraticCurveTo(40,-33,91,-3);ctx.quadraticCurveTo(42,-14,0,0);ctx.fillStyle=i%2?P.lime:'#71a977';ctx.fill();ctx.restore();
    }
    circle(ctx,0,-123,7,'#cda675');circle(ctx,10,-128,7,'#cda675');ctx.restore();
  }
  function beach(x,y,s,local,detail=true){
    ctx.save();ctx.translate(x,y);ctx.scale(s,s);
    base(0,130,382,41,'#246f83','#164956');
    for(let i=0;i<5;i++){
      const yy=100+i*21+Math.sin(t*.9+i)*6;
      ctx.beginPath();ctx.ellipse(0,yy,355-i*18,68-i*3,0,.12,PI-.12);ctx.strokeStyle=i%2?'#65aab4':'#5199a8';ctx.lineWidth=3;ctx.stroke();
    }
    path(ctx,[[-307,90],[-257,18],[-118,-34],[44,-19],[215,35],[294,114],[180,174],[9,187],[-170,150]],'#ac996a');
    path(ctx,[[-307,73],[-257,1],[-118,-51],[44,-36],[215,18],[294,97],[180,157],[9,170],[-170,133]],'#e9d6a5');
    ctx.save();ctx.globalAlpha*=.8;ctx.beginPath();ctx.moveTo(-286,91);ctx.bezierCurveTo(-84,161,114,194,280,116);ctx.strokeStyle='#edf2d8';ctx.lineWidth=6+Math.sin(t*2)*2;ctx.stroke();ctx.restore();
    // A small open-air retreat pavilion with dimensional roof and timber posts.
    path(ctx,[[-61,-71],[132,-42],[185,-4],[-10,-30]],'#b6b28b');
    path(ctx,[[-48,-188],[132,-159],[193,-67],[3,-95]],'#be9771');
    path(ctx,[[-48,-188],[3,-95],[-83,-112]],'#e5c18d');
    path(ctx,[[-48,-188],[132,-159],[103,-186],[-37,-208]],'#e9c698');
    for(let k=0;k<7;k++)line(ctx,-26+k*24,-180+k*4,18+k*24,-107+k*4,'#d4ac7f',3);
    [-62,12,163].forEach((xx,j)=>line(ctx,xx,-106+j*8,xx,-23+j*11,'#eddbc0',8));
    rr(ctx,27,-77,61,18,5,P.ivory);rr(ctx,34,-60,5,21,2,'#cab291');rr(ctx,79,-60,5,21,2,'#cab291');
    palm(-194,20,1.22,1);palm(223,58,.97,3);
    // Umbrella, loungers and gently moving hanging lights.
    line(ctx,-82,17,-82,80,'#a68560',5);
    ctx.beginPath();ctx.moveTo(-139,26);ctx.quadraticCurveTo(-84,-44,-26,26);ctx.closePath();ctx.fillStyle=P.coral;ctx.fill();
    path(ctx,[[-139,26],[-82,-18],[-82,26]],'#f3b895');
    path(ctx,[[-126,86],[-57,99],[-44,112],[-113,100]],P.ivory);line(ctx,-114,96,-114,114,'#bd9c73',4);line(ctx,-51,108,-51,123,'#bd9c73',4);
    path(ctx,[[10,91],[78,104],[91,117],[22,105]],P.ivory);line(ctx,22,103,22,120,'#bd9c73',4);line(ctx,82,114,82,130,'#bd9c73',4);
    if(detail){person(ctx,149,35,.58,P.blue);person(ctx,108,57,.53,P.coral);}
    const boatX=-215+Math.sin(t*.3)*30;
    path(ctx,[[boatX,190],[boatX+71,200],[boatX+55,213],[boatX+5,204]],P.ivory);line(ctx,boatX+27,193,boatX+27,142,P.ivory,3);path(ctx,[[boatX+28,145],[boatX+28,186],[boatX+63,187]],P.lime);
    if(detail){cloud(-249+Math.sin(t*.15)*23,-274,.83);cloud(244+Math.sin(t*.18)*17,-307,.67);circle(ctx,177,-321,38,'#eed6a0');}
    ctx.restore();
  }
  function building(x,y,w,h,color,side,roof,phase){
    const k=.74+.26*E(phase);
    ctx.save();ctx.translate(x,y);ctx.scale(1,k);
    path(ctx,[[0,0],[w,0],[w,-h],[0,-h]],color);
    path(ctx,[[w,0],[w+35,-18],[w+35,-h-18],[w,-h]],side);
    path(ctx,[[0,-h],[w,-h],[w+35,-h-18],[35,-h-18]],roof);
    for(let row=0;row<Math.floor((h-24)/33);row++)for(let col=0;col<Math.floor((w-14)/26);col++){
      const shimmer=Math.sin(t*.8+row*.7+col+x)>.2;
      rr(ctx,12+col*26,-h+15+row*33,12,18,2,shimmer?'#e1d496':'#578493');
    }
    for(let row=0;row<Math.floor((h-24)/33);row++)path(ctx,[[w+11,-h+13+row*33],[w+24,-h+7+row*33],[w+24,-h+22+row*33],[w+11,-h+28+row*33]],'#628a97');
    ctx.restore();
  }
  function city(x,y,s,local,detail=true){
    ctx.save();ctx.translate(x,y);ctx.scale(s,s);
    base(0,158,372,41,'#799a94','#41666f');
    path(ctx,[[-308,126],[-100,43],[317,138],[100,222]],'#b4bcb0');
    path(ctx,[[-255,160],[-36,74],[50,97],[-166,183]],'#345465');
    path(ctx,[[-250,75],[-123,20],[287,139],[159,191]],'#345465');
    ctx.save();ctx.setLineDash([13,13]);line(ctx,-215,92,243,153,'#c6cab6',2);line(ctx,-212,163,8,95,'#c6cab6',2);ctx.restore();
    building(-249,63,80,225,'#aac4bc','#456e7c','#d3ded0',local/.7);
    building(-143,-6,93,363,'#497487','#284c63','#81a5ac',(local-.1)/.8);
    building(-15,26,102,287,'#b8c8b5','#698887','#e1e0cb',(local-.2)/.8);
    building(139,89,83,335,'#548693','#2b576f','#8ab3b4',(local-.3)/.8);
    line(ctx,-96,-369,-96,-412,P.ivory,4);circle(ctx,-96,-417,5,P.lime);
    // A low, sweeping conference hall anchors the foreground.
    path(ctx,[[-61,41],[140,79],[187,120],[-13,81]],'#dce3d7');
    path(ctx,[[-61,41],[-13,81],[-13,143],[-61,105]],'#7c9e9d');
    path(ctx,[[-13,81],[187,120],[187,180],[-13,143]],P.ivory);
    path(ctx,[[-78,27],[139,66],[207,113],[186,123],[-20,85]],P.lime);
    for(let col=0;col<7;col++)path(ctx,[[col*26-1,100+col*5],[col*26+15,103+col*5],[col*26+15,138+col*5],[col*26-1,135+col*5]],'#345e73');
    rr(ctx,-51,-4,213,37,18,'#193e50');text(ctx,'MEET · SHARE · INSPIRE',55,21,16,P.ivory,'center',700);
    // Small tram glides along the front edge, on its own drawn track.
    ctx.beginPath();ctx.moveTo(-314,217);ctx.quadraticCurveTo(0,288,323,218);ctx.strokeStyle='#b3c5b4';ctx.lineWidth=4;ctx.stroke();
    const trX=-194+((t*32)%388),trY=238-(trX*trX/2100);
    ctx.save();ctx.translate(trX,trY);rr(ctx,-57,-37,114,45,11,P.coral);rr(ctx,-47,-29,94,20,4,'#244b60');for(let v=0;v<4;v++)line(ctx,-29+v*23,-28,-29+v*23,-10,'#8eafaf',2);circle(ctx,-32,10,8,'#163345');circle(ctx,32,10,8,'#163345');ctx.restore();
    if(detail){for(let p=0;p<4;p++)person(ctx,-73+p*42,159+p*4,.37,p%2?P.blue:P.coral);cloud(220+Math.sin(t*.18)*15,-389,.7);cloud(-284+Math.sin(t*.2)*15,-300,.56);}
    ctx.restore();
  }
  function pine(x,y,s){ctx.save();ctx.translate(x,y);ctx.scale(s,s);line(ctx,0,0,0,-83,'#917953',7);path(ctx,[[0,-130],[-39,-48],[39,-48]],'#50877c');path(ctx,[[0,-96],[-49,-15],[49,-15]],'#315e62');path(ctx,[[0,-130],[0,-15],[49,-15]],'#2c575c');ctx.restore();}
  function mountain(x,y,s,local,detail=true){
    ctx.save();ctx.translate(x,y);ctx.scale(s,s);
    base(0,179,373,43,'#719583','#375e60');
    circle(ctx,169,-252,58,'#f1cf91');
    withAlpha(ctx,.3,()=>{circle(ctx,169,-252,82,null,'#efc993',2);circle(ctx,169,-252,103,null,'#efc993',1);});
    path(ctx,[[-335,121],[-168,-289],[33,118]],'#6e99a0');
    path(ctx,[[-168,-289],[-98,-24],[33,118],[-43,121]],'#355d73');
    path(ctx,[[-205,-198],[-168,-289],[-120,-186],[-152,-199],[-173,-180]],'#e5ede3');
    path(ctx,[[-155,163],[37,-371],[268,133]],'#90b4af');
    path(ctx,[[37,-371],[54,-37],[268,133],[74,149]],'#537e88');
    path(ctx,[[5,-282],[37,-371],[91,-248],[54,-267],[33,-249]],P.ivory);
    path(ctx,[[47,182],[235,-212],[364,147]],'#709991');
    path(ctx,[[235,-212],[248,56],[364,147],[210,174]],'#3f6d73');
    path(ctx,[[210,-155],[235,-212],[259,-148],[235,-157]],'#d7e4d7');
    path(ctx,[[-357,166],[-224,72],[-117,101],[-25,68],[107,124],[225,91],[367,165],[208,237],[-34,268],[-237,225]],'#91ad82');
    path(ctx,[[-357,166],[-224,72],[-117,101],[-192,159],[-239,224]],'#6b997f');
    // Winding hiking trail and animated route dots are deliberately illustrative.
    ctx.beginPath();ctx.moveTo(-151,235);ctx.bezierCurveTo(-245,134,38,207,-39,143);ctx.bezierCurveTo(-79,110,33,90,58,46);ctx.strokeStyle='#d9ca9b';ctx.lineWidth=18;ctx.lineCap='round';ctx.stroke();
    for(let i=0;i<8;i++){const yy=234-i*21;circle(ctx,-115+Math.sin(i*.89)*49,yy,2.8,P.ivory);}
    [[-287,169,.95],[-207,54,.62],[268,168,1.12],[195,211,.68],[-60,219,.47]].forEach(v=>pine(...v));
    // A small camp and a wayfinding marker provide human scale.
    path(ctx,[[65,173],[112,103],[168,173]],P.coral);path(ctx,[[112,103],[112,173],[168,173]],'#b86e56');path(ctx,[[91,173],[111,136],[127,173]],'#264957');
    line(ctx,-30,93,-30,42,'#d4c4a0',5);path(ctx,[[-57,41],[-6,41],[8,51],[-6,61],[-57,61]],'#d4c4a0');
    if(detail){
      const walk=Math.sin(t*2.5)*2;
      person(ctx,-113,187+walk,.51,P.blue);person(ctx,-150,197-walk,.47,P.coral);person(ctx,-78,169+walk,.44,P.lime);
      line(ctx,-128,166,-119,194,'#163e4c',3);line(ctx,-92,148,-84,176,'#163e4c',3);
      cloud(-206+Math.sin(t*.22)*20,-331,.63);cloud(237+Math.sin(t*.17)*18,-347,.59);
      for(let i=0;i<3;i++){const bx=-256+i*60+Math.sin(t*.3)*15,by=-224-i*17;ctx.beginPath();ctx.moveTo(bx-11,by);ctx.quadraticCurveTo(bx-5,by-7,bx,by);ctx.quadraticCurveTo(bx+5,by-7,bx+11,by);ctx.strokeStyle='#bdced0';ctx.lineWidth=2;ctx.stroke();}
    }
    ctx.restore();
  }
  function compass(x,y,r,rotation,a=1){
    withAlpha(ctx,a,()=>{
      circle(ctx,x,y,r,null,'#75928f',2);circle(ctx,x,y,r-14,null,'#46656e',1);
      for(let i=0;i<48;i++){const ang=i*PI/24+rotation;const outer=r-6,inner=r-(i%4===0?22:12);line(ctx,x+Math.cos(ang)*inner,y+Math.sin(ang)*inner,x+Math.cos(ang)*outer,y+Math.sin(ang)*outer,i%4===0?P.lime:'#799d9d',i%4===0?2:1);}
    });
  }
  function globe(x,y,r,p){
    ctx.save();ctx.translate(x,y);ctx.rotate(-.16+t*.11);ctx.scale(p,p);
    circle(ctx,0,0,r,'#246b82',P.teal,3);
    for(let i=-2;i<=2;i++)ellipse(0,i*r*.27,Math.sqrt(Math.max(0,r*r-i*i*r*r*.073)),r*.14,null,'#7aadb244',2);
    ellipse(0,0,r*.39,r,null,'#7aadb299',2);ellipse(0,0,r*.73,r,null,'#7aadb277',2);
    // Abstract land-like shapes are visual texture, not a geographic map.
    path(ctx,[[-153,-118],[-105,-160],[-32,-159],[14,-111],[-36,-67],[-99,-51],[-110,9],[-154,-26]],'#a7c680');
    path(ctx,[[32,21],[105,-12],[165,17],[141,77],[87,95],[49,155],[16,128],[-4,80]],'#a7c680');
    circle(ctx,-80,-88,8,P.ivory);circle(ctx,104,49,8,P.ivory);
    ctx.restore();
  }

  ctx.fillStyle=P.navy;ctx.fillRect(0,0,1080,1920);
  const backdrop=ctx.createRadialGradient(540,1050,80,540,1050,1000);backdrop.addColorStop(0,'#254a55');backdrop.addColorStop(1,P.navy);ctx.fillStyle=backdrop;ctx.fillRect(0,180,1080,1530);
  compass(540,1030,449,t*.025,.3);
  for(let i=0;i<14;i++){const a=i*PI/7+t*.006;circle(ctx,540+Math.cos(a)*453,1030+Math.sin(a)*453,1.8,'#72908f');}

  const scenes=[
    {start:0,end:5.9,tag:'THE BEACH RETREAT',headline:['Space to','reconnect.'],caption:'Slow the pace. Bring your people closer.'},
    {start:5.25,end:11.4,tag:'THE CITY CONFERENCE',headline:['A place for','big ideas.'],caption:'Fresh surroundings. Shared conversations.'},
    {start:10.75,end:16.9,tag:'THE MOUNTAIN ADVENTURE',headline:['Room to','explore.'],caption:'A new perspective, experienced together.'},
    {start:16.25,end:22.3,tag:'YOUR NEXT TEAM JOURNEY',headline:['Where will your','team go next?'],caption:'Choose the setting. Shape the experience.'}
  ];
  scenes.forEach((scene,i)=>{
    const a=i===0?1-smooth(5.25,5.9,t):fade(scene.start,scene.end);if(a<.001)return;
    const local=t-scene.start,enter=E(local/.9);
    withAlpha(ctx,a,()=>{
      text(ctx,scene.tag,90,278+18*(1-enter),26,P.lime,'left',700);
      lines(ctx,scene.headline,87,374+25*(1-enter),82,95,P.ivory,'left',700);
      text(ctx,scene.caption,540,1515,34,'#cbd8d8','center',500);
      if(i===0){
        const open=smooth(1.6,2.4,t);
        withAlpha(ctx,1-smooth(1.45,1.95,t),()=>{globe(540,1010,272,.86+.14*E(t/1.1));compass(540,1010,314,t*.2,.75);});
        withAlpha(ctx,open,()=>beach(540,1070+46*(1-open),.97+.03*open,local));
        if(t>2.7){withAlpha(ctx,smooth(2.7,3.4,t),()=>{rr(ctx,366,1370,348,56,28,'#1a3b4b',P.teal,1);text(ctx,'RECONNECT',540,1408,28,P.lime,'center',700);});}
      }
      if(i===1){city(540+75*(1-enter),1057+30*(1-enter),.98,local);withAlpha(ctx,enter,()=>{rr(ctx,366,1370,348,56,28,'#1a3b4b',P.teal,1);text(ctx,'EXCHANGE IDEAS',540,1408,28,P.lime,'center',700);});}
      if(i===2){mountain(540-75*(1-enter),1080+40*(1-enter),.99,local);withAlpha(ctx,enter,()=>{rr(ctx,348,1395,384,56,28,'#1a3b4b',P.teal,1);text(ctx,'EXPLORE TOGETHER',540,1433,28,P.lime,'center',700);});}
      if(i===3){
        const float=Math.sin(t*.9)*4;
        // The choice is visual: each setting remains alive in its miniature.
        ctx.save();ctx.setLineDash([6,12]);ctx.lineDashOffset=-t*14;
        ctx.beginPath();ctx.moveTo(296,830);ctx.quadraticCurveTo(540,670,789,846);ctx.quadraticCurveTo(846,1110,542,1260);ctx.quadraticCurveTo(267,1105,296,830);ctx.strokeStyle='#7a9b8055';ctx.lineWidth=2;ctx.stroke();ctx.restore();
        beach(283-40*(1-enter),908+float,.49,local,false);
        city(795+40*(1-enter),908-float,.49,local,false);
        mountain(540,1250+50*(1-enter),.53,local,false);
        rr(ctx,114,1080,338,54,27,'#163c4c');text(ctx,'BEACH RETREAT',283,1117,31,P.ivory,'center',700);
        rr(ctx,614,1080,360,54,27,'#163c4c');text(ctx,'CITY CONFERENCE',794,1117,31,P.ivory,'center',700);
        rr(ctx,321,1405,438,54,27,'#163c4c');text(ctx,'MOUNTAIN ADVENTURE',540,1442,31,P.ivory,'center',700);
        compass(540,922,56,t*.13,.85);
        ctx.save();ctx.translate(540,922);ctx.rotate(Math.sin(local*.6)*1.2);path(ctx,[[0,-34],[11,9],[0,3],[-11,9]],P.lime);path(ctx,[[0,34],[11,-9],[0,-3],[-11,-9]],P.teal);ctx.restore();
      }
    });
  });
}

module.exports={title,subtitle,draw,storyboard};
