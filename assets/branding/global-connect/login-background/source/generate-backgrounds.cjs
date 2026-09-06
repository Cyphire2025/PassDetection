'use strict';

// Original decorative route artwork. Land outlines: public-domain Natural Earth,
// supplied with the adjacent Journey Pavilion source. No political borders.
const fs = require('node:fs');
const path = require('node:path');
const output = path.resolve(__dirname, '..');
const geography = JSON.parse(fs.readFileSync(path.resolve(output, '../journey-film/source/ne_110m_land.geojson'), 'utf8'));
const project = ([lon, lat]) => [20 + (lon + 180) * 960 / 360, 30 + (85 - lat) * 570 / 145];
const point = p => project(p).map(n => n.toFixed(1)).join(',');
const outlines = [];
for (const feature of geography.features) {
  const polygons = feature.geometry.type === 'Polygon' ? [feature.geometry.coordinates] : feature.geometry.coordinates;
  for (const polygon of polygons) {
    const ring = polygon[0];
    if (Math.max(...ring.map(p => p[1])) < -58 || ring.length < 7) continue;
    outlines.push('M' + ring.map(point).join('L') + 'Z');
  }
}
const cities = [[-0.1,51.5],[55.3,25.2],[72.9,19.1],[103.8,1.35],[151.2,-33.8],[-74,40.7]];
const links = [[0,2],[1,3],[2,3],[3,4],[0,5]];
const routes = links.map(([a,b]) => {
  const p=project(cities[a]),q=project(cities[b]);
  return `<path d="M${p.join(',')}Q${(p[0]+q[0])/2},${Math.min(p[1],q[1])-65} ${q.join(',')}"/>`;
}).join('');
const markers = cities.map(c => {const[x,y]=project(c);return `<circle cx="${x}" cy="${y}" r="3.2"/><circle cx="${x}" cy="${y}" r="8" fill="none" opacity=".45"/>`;}).join('');
const grid = Array.from({length:9},(_,i)=>`<path d="M${20+i*120} 24V625"/>`).join('') + Array.from({length:6},(_,i)=>`<path d="M12 ${50+i*110}H986"/>`).join('');
const atlas = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 660" fill="none"><g stroke="#8dafc4" stroke-width=".6" opacity=".22">${grid}</g><path d="${outlines.join('')}" fill="#819faf" fill-opacity=".08" stroke="#9ebacd" stroke-width=".9" stroke-linejoin="round"/><g stroke="#aec9d9" stroke-width="1.5" opacity=".9">${routes}</g><g fill="#b3d94d" stroke="#b3d94d" stroke-width="1">${markers}</g></svg>`;
fs.writeFileSync(path.join(output, 'travel-atlas.svg'), atlas);

// Fine, concentric travel-document engraving in two corners, leaving the form clear.
const curves = Array.from({length:16},(_,i) => `<path d="M${330+i*16} -80C${170+i*17} 92 ${310+i*20} 208 ${655+i*17} 254"/>`).join('');
const lower = Array.from({length:11},(_,i) => `<path d="M-90 ${775+i*16}C${62+i*14} ${670+i*10} ${152+i*17} ${917+i*12} ${350+i*13} 1060"/>`).join('');
const paper = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 600 1000" preserveAspectRatio="none" fill="none"><g stroke="#335f7b" stroke-width=".8" opacity=".22">${curves}${lower}</g><g stroke="#719843" stroke-width="1.2" opacity=".28"><path d="M377-40C246 102 392 201 668 220"/><path d="M-45 822C137 750 152 972 403 1050"/></g><g transform="translate(540 245)" stroke="#335f7b" opacity=".28"><circle r="20" stroke-width=".6"/><path d="M0-27V-16M0 16V27M-27 0H-16M16 0H27" stroke-width=".8"/><path d="M0-12 3-3 12 0 3 3 0 12-3 3-12 0-3-3Z" stroke-width=".6"/></g></svg>`;
fs.writeFileSync(path.join(output, 'paper-routes.svg'), paper);
console.log('Generated travel-atlas.svg and paper-routes.svg');
