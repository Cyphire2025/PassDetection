import { existsSync, mkdirSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createServer } from "vite";
import react from "@vitejs/plugin-react";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const entry = path.join(frontend, ".broadcast-motion-preview.entry.tsx");
if (existsSync(entry)) throw new Error("The temporary broadcast preview entry already exists.");
const destination = path.resolve(frontend, "../assets/branding/global-connect/broadcast-motion");
const entrySource = `
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {WhatsAppBroadcastMotion} from '@/features/whatsapp/components/whatsapp-broadcast-motion';
const variants = [['welcome','Welcome message','A greeting begins the conversation.'],['passport_link','Passport link','One secure link, sent individually.'],['reminder','Reminder','A timely nudge to the right people.']] as const;
export function render() {return renderToStaticMarkup(<main>
  <header><p className="eyebrow">GLOBAL CONNECT · MOTION LIBRARY</p><h1>One message. Many conversations.</h1><p className="intro">Broadcast artwork and compact display sizes. Simulated activity for preview only.</p></header>
  <nav aria-label="Preview animation state"><button data-preview-state="sending" aria-pressed="true">Sending</button><button data-preview-state="submitting" aria-pressed="false">Submitting</button><button data-preview-state="complete" aria-pressed="false">Finished</button><button data-preview-state="attention" aria-pressed="false">Needs review</button><button data-preview-state="reconnecting" aria-pressed="false">Reconnecting</button></nav>
  <div className="scenes">{variants.map(([messageType,title,description],index)=><section key={messageType} className="scene-card"><p className="meta">0{index+1} / {title.toUpperCase()}</p><WhatsAppBroadcastMotion messageType={messageType}/><h2>{title}</h2><p>{description}</p></section>)}</div>
  <div className="contexts"><section className="context-card"><p className="meta">ON THE BROADCAST PAGE</p><h2>Live WhatsApp delivery</h2><div className="inline-example"><div className="inline-art"><WhatsAppBroadcastMotion compact messageType="passport_link"/></div><div className="details"><strong>Passport link broadcast</strong><p>Sample recipient list · <b className="count">72 sent of 120</b></p><div className="progress"><i/></div><small className="state-label">48 queued · dispatch in progress</small></div></div></section>
  <section className="context-card"><p className="meta">ON ANOTHER PAGE</p><h2>The floating tracker</h2><div className="float-example"><div className="float-art"><WhatsAppBroadcastMotion compact messageType="welcome"/></div><div className="details"><strong>Welcome broadcast</strong><p>Sample list · <b className="count">72 sent of 120</b></p><div className="progress"><i/></div><small className="state-label">48 queued · dispatch in progress</small></div><span className="close" aria-hidden="true">×</span></div><p className="note">The application keeps its existing dragging and dismissal controls.</p></section></div>
  <footer>These generic recipient cards illustrate dispatch. Actual application counts and outcomes remain authoritative; sent does not mean delivered or read. The application pauses hidden artwork and respects reduced-motion preferences.</footer>
</main>);}
`;
writeFileSync(entry, entrySource);
let vite;
try {
  vite = await createServer({ configFile: false, root: frontend, plugins: [react()], resolve: { alias: { "@": frontend } }, server: { middlewareMode: true }, css: { postcss: { plugins: [] } } });
  const previewEntry = await vite.ssrLoadModule(`/@fs/${entry.replaceAll("\\", "/")}`);
  const artworkCss = (await vite.transformRequest("/features/whatsapp/components/whatsapp-broadcast-motion.module.css?direct")).code;
  const css = `
*{box-sizing:border-box}body{margin:0;background:#f3f7f9;color:#14364d;font:14px/1.5 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:38px 32px}header{margin-bottom:24px}.eyebrow{font-size:10px;font-weight:750;letter-spacing:2px;color:#617e8c}h1{font-size:34px;letter-spacing:-1.2px;line-height:1.2;margin:8px 0}h2{font-size:17px;letter-spacing:-.4px;margin:6px 0}.intro{color:#61798a;margin:10px 0}nav{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:24px}button{font:inherit;font-size:12px;cursor:pointer;border:1px solid #cadbe3;border-radius:8px;padding:8px 13px;background:white;color:#34576a}button[aria-pressed=true]{background:#143d55;color:white;border-color:#143d55}button:focus-visible{outline:3px solid #99c844;outline-offset:2px}.scenes{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}.scene-card,.context-card{border:1px solid #d9e5eb;background:white;border-radius:15px;padding:20px}.scene-card [data-whatsapp-broadcast-motion]{margin:18px auto 6px}.scene-card>p:not(.meta){font-size:12px;color:#69818f;margin:3px 0}.meta{font-size:9px;letter-spacing:1.4px;color:#648394;margin:0}.contexts{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-top:20px}.context-card h2{margin-top:8px}.inline-example{display:flex;align-items:center;gap:12px;margin-top:20px;padding:12px 0}.inline-art{width:132px;flex-shrink:0}.details{min-width:0;flex:1}.details strong{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;font-size:12px}.details p{margin:2px 0 7px;color:#648093;font-size:10px}.details b{font-weight:600}.progress{height:5px;background:#e3edf1;border-radius:9px;overflow:hidden}.progress i{display:block;height:100%;width:60%;border-radius:9px;background:#377da3;transition:width .4s}.state-label{display:block;margin-top:6px;font-size:9px;color:#6a8190}.float-example{display:flex;align-items:center;gap:12px;padding:12px;background:#edf8f1;border:1px solid #c8e5d5;border-radius:28px;margin-top:20px;box-shadow:0 10px 24px #20493012}.float-art{width:90px;flex-shrink:0}.float-example .progress{background:#d4ecdc}.close{color:#749386;font-size:20px;padding:4px}.note{font-size:10px;color:#7a909e;margin-bottom:0}footer{font-size:11px;color:#708695;line-height:1.8;margin-top:24px;max-width:860px}@media(max-width:850px){.scenes{grid-template-columns:1fr}.scene-card{display:grid;grid-template-columns:1fr 1fr;align-items:center}.scene-card .meta{grid-column:1/-1}.scene-card [data-whatsapp-broadcast-motion]{grid-row:2/4;margin:10px 0 0}.scene-card h2,.scene-card>p:not(.meta){margin-left:12px}.contexts{grid-template-columns:1fr}}@media(max-width:480px){main{padding:24px 16px}h1{font-size:29px}.scene-card,.context-card{padding:16px}.scene-card h2{font-size:15px}.inline-art{width:96px}.float-art{width:76px}.float-example{gap:8px;padding:10px}.details p{font-size:9px}.close{padding:0}.details strong{font-size:11px}}
`;
  const script = `
document.querySelectorAll('[data-preview-state]').forEach(button=>button.addEventListener('click',()=>{
 const state=button.dataset.previewState;
 document.querySelectorAll('[data-preview-state]').forEach(item=>item.setAttribute('aria-pressed',String(item===button)));
 document.querySelectorAll('[data-whatsapp-broadcast-motion]').forEach(scene=>{scene.dataset.state=state;scene.dataset.playing=String(state==='sending'||state==='submitting');});
 const terminal=state==='complete'||state==='attention';
 document.querySelectorAll('.count').forEach(node=>node.textContent=state==='complete'?'120 sent of 120':state==='attention'?'117 sent of 120':state==='submitting'?'Submitting request':'72 sent of 120');
 document.querySelectorAll('.progress i').forEach(node=>{node.style.width=terminal?'100%':state==='submitting'?'0%':'60%';node.style.background=state==='attention'?'#be923d':state==='complete'?'#69a14e':'#377da3';});
 document.querySelectorAll('.state-label').forEach(node=>node.textContent=state==='complete'?'Dispatch finished':state==='attention'?'2 failed · 1 outcome unknown':state==='reconnecting'?'Reconnecting · last known counts':state==='submitting'?'Preparing the send request':'48 queued · dispatch in progress');
}));`;
  mkdirSync(destination, { recursive: true });
  writeFileSync(path.join(destination, "preview.html"), `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Global Connect broadcast motion</title><style>${css}\n${artworkCss}</style></head><body>${previewEntry.render()}<script>${script}</script></body></html>`);
  console.log(path.join(destination, "preview.html"));
} finally {
  await vite?.close();
  // Remove only the temporary entry created by this script.
  if (existsSync(entry) && readFileSync(entry, "utf8") === entrySource) unlinkSync(entry);
}
