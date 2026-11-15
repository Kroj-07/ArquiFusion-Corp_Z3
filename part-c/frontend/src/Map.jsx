import React,{useEffect,useRef}from'react';import L from'leaflet';import'leaflet/dist/leaflet.css';
const colors={operating:'#10a482',idle:'#8995a6',maintenance:'#eeb54a',fault:'#e15d4c',stopped:'#cf6b55'};
export default function FleetMap({machines,onSelect,large=false}){
 const div=useRef(),map=useRef(),layer=useRef();const click=useRef(onSelect);click.current=onSelect;
 useEffect(()=>{const m=L.map(div.current,{zoomControl:false,scrollWheelZoom:false,attributionControl:true}).setView([-12.04,-76.93],13);map.current=m;
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:18,attribution:'© OpenStreetMap'}).addTo(m);L.control.zoom({position:'bottomright'}).addTo(m);layer.current=L.layerGroup().addTo(m);
  const observer=new ResizeObserver(()=>m.invalidateSize());observer.observe(div.current);return()=>{observer.disconnect();m.remove();map.current=null;};},[]);
 useEffect(()=>{if(!map.current||!layer.current)return;layer.current.clearLayers();const points=[];
  for(const machine of machines){if(!machine.location)continue;const p=[machine.location.lat,machine.location.lon];points.push(p);
   const marker=document.createElement('span');marker.style.setProperty('--marker',colors[machine.status]||colors.idle);marker.textContent=machine.machine_id.slice(-2);
   const tooltip=document.createElement('span');tooltip.textContent=`${machine.machine_id} · ${machine.name||machine.model}`;
   const icon=L.divIcon({className:'fleet-marker',html:marker,iconSize:[35,35],iconAnchor:[17,17]});
   L.marker(p,{icon,title:machine.name||machine.machine_id,keyboard:true}).bindTooltip(tooltip,{direction:'top'}).on('click',()=>click.current(machine)).addTo(layer.current);}
  if(points.length)map.current.fitBounds(points,{padding:[45,45],maxZoom:14});
 },[machines]);
 return <div className={`map-shell ${large?'large':''}`}><div ref={div} className="fleet-map" aria-label="Mapa de ubicación de la flota"/><div className="map-label"><span className="dot green"/> Ubicación reportada · WGS84</div><div className="map-legend">{[['operating','Operativa'],['fault','Atención'],['maintenance','Mantenimiento'],['idle','En espera']].map(([key,label])=><span key={key}><i style={{background:colors[key]}}/>{label}</span>)}</div></div>;
}
