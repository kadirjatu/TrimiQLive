const content = document.getElementById("content");
const csrf = document.querySelector('meta[name="csrf-token"]')?.content;
const menuButton = document.getElementById("menuButton");
const sidebar = document.getElementById("sidebar");

menuButton?.addEventListener("click", () => sidebar.classList.toggle("open"));

async function api(path, options = {}) {
  const headers = options.headers || {};
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = csrf;
  if (options.body && !(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(path, {...options, headers});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `Request failed (${response.status})`);
  return data;
}

function toast(message, isError = false) {
  const node = document.getElementById("toast");
  node.textContent = message;
  node.style.borderColor = isError ? "var(--danger)" : "var(--success)";
  node.classList.add("show");
  setTimeout(() => node.classList.remove("show"), 2600);
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B","KB","MB","GB","TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / Math.pow(1024,index)).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (!seconds) return "0:00";
  seconds = Math.round(seconds);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return h ? `${h}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}` : `${m}:${String(s).padStart(2,"0")}`;
}

function formatUptime(seconds) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${String(h).padStart(2,"0")}:${String(m).padStart(2,"0")}:${String(s).padStart(2,"0")}`;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, char => ({
    "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#039;"
  })[char]);
}

async function refreshTopStatus() {
  try {
    const data = await api("/api/dashboard");
    const badge = document.getElementById("modeBadge");
    const header = document.getElementById("headerStatus");
    badge.textContent = data.mode === "DEMO" ? "DEMO MODE" : "PRODUCTION";
    const running = data.status === "RUNNING" || data.status === "DEMO_RUNNING";
    header.textContent = running ? (data.mode === "DEMO" ? "DEMO Running" : "Process Running") : "Stopped";
  } catch (_) {}
}

async function renderDashboard() {
  document.getElementById("pageTitle").textContent = "Dashboard";
  content.innerHTML = `<div class="grid stats" id="stats"></div><div class="grid" style="grid-template-columns:2fr 1fr;margin-top:16px">
    <div class="card"><h3>Streaming Status</h3><div id="streamStatus"></div></div>
    <div class="card"><h3>Quick Controls</h3><div style="display:flex;gap:8px;flex-wrap:wrap">
      <button class="primary" id="quickStart">Start Stream</button><button class="danger" id="quickStop">Stop Stream</button><button class="secondary" id="quickRestart">Restart</button>
    </div></div></div>`;
  const data = await api("/api/dashboard");
  const system = await api("/api/system");
  document.getElementById("stats").innerHTML = `
    ${stat("Uploaded Videos",data.video_count,"Video library")}
    ${stat("Playlists",data.playlist_count,"Saved playlists")}
    ${stat("Stream Status",data.status === "DEMO_RUNNING" ? "DEMO RUNNING" : data.status,"Actual process state")}
    ${stat("Stream Uptime",formatUptime(data.uptime || 0),"Since start")}
    ${stat("CPU Usage",`${system.cpu_percent.toFixed(1)}%`,"Server load")}
    ${stat("RAM Usage",`${system.ram_percent.toFixed(1)}%`,"Available memory")}
    ${stat("Free Storage",formatBytes(system.disk_free_mb * 1024 * 1024),"Upload volume")}
    ${stat("Network",system.network_status,"Local availability")}
  `;
  document.getElementById("streamStatus").innerHTML = `
    <div style="display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px">
      ${info("Destination",data.current_destination)}
      ${info("Playlist",data.current_playlist)}
      ${info("Current Video","Managed by playlist engine")}
      ${info("Last Error",data.last_error || "None")}
    </div>
    ${data.mode === "DEMO" ? '<div class="alert" style="margin-top:14px;color:#b6c4e8;background:rgba(77,124,255,.08)">DEMO mode simulates process status. It does not create a real RTMP broadcast.</div>' : ""}
  `;
  document.getElementById("quickStart").onclick = () => location.href="/streaming";
  document.getElementById("quickStop").onclick = stopStream;
  document.getElementById("quickRestart").onclick = restartStream;
}

function stat(label,value,note) { return `<div class="card stat"><div class="stat-label">${escapeHtml(label)}</div><div class="stat-value">${escapeHtml(value)}</div><div class="stat-note">${escapeHtml(note)}</div></div>`; }
function info(label,value) { return `<div><div class="stat-label">${escapeHtml(label)}</div><div style="margin-top:6px">${escapeHtml(value || "Not selected")}</div></div>`; }

async function renderVideos() {
  document.getElementById("pageTitle").textContent = "Video Library";
  content.innerHTML = `<div class="toolbar"><div><h2 style="margin:0">Video Library</h2></div><div class="toolbar-right">
    <input id="videoSearch" placeholder="Search videos"><select id="videoSort"><option value="created_at">Newest</option><option value="original_name">Name</option><option value="size">Size</option><option value="duration">Duration</option></select>
    <button class="primary" id="uploadOpen">Upload MP4</button></div></div>
    <div class="card"><table><thead><tr><th>Video</th><th>Size</th><th>Duration</th><th>Resolution</th><th>Codecs</th><th></th></tr></thead><tbody id="videoRows"></tbody></table></div>
    <div class="modal" id="uploadModal"><div class="modal-box"><div class="modal-head"><h3>Upload MP4</h3><button class="close" data-close>×</button></div>
      <input id="videoFile" type="file" accept=".mp4,video/mp4" style="width:100%"><div id="uploadWarning" class="alert" style="display:none"></div>
      <button class="primary" id="uploadButton" style="margin-top:12px;width:100%">Upload</button></div></div>`;
  document.getElementById("uploadOpen").onclick = () => document.getElementById("uploadModal").classList.add("open");
  document.querySelector("[data-close]").onclick = () => document.getElementById("uploadModal").classList.remove("open");
  async function load() {
    const rows = await api(`/api/videos?search=${encodeURIComponent(document.getElementById("videoSearch").value)}&sort=${document.getElementById("videoSort").value}`);
    document.getElementById("videoRows").innerHTML = rows.length ? rows.map(row => `<tr>
      <td><div style="display:flex;align-items:center;gap:10px">${row.thumbnail ? `<img class="video-thumb" src="/uploads/thumbnails/${encodeURIComponent(row.thumbnail)}">` : '<div class="video-thumb"></div>'}<strong>${escapeHtml(row.original_name)}</strong></div></td>
      <td>${formatBytes(row.size)}</td><td>${formatDuration(row.duration)}</td><td>${row.width && row.height ? `${row.width}×${row.height}` : "Unknown"}</td>
      <td>${escapeHtml(row.codec || "Unknown")} / ${escapeHtml(row.audio_codec || "No audio")}</td>
      <td><button class="danger" data-delete="${row.id}">Delete</button></td></tr>`).join("") : `<tr><td colspan="6" style="color:var(--muted)">No videos uploaded</td></tr>`;
    document.querySelectorAll("[data-delete]").forEach(button => button.onclick = async () => {
      if (!confirm("Delete this video?")) return;
      await api(`/api/videos/${button.dataset.delete}`, {method:"DELETE"});
      toast("Video deleted"); load();
    });
  }
  document.getElementById("videoSearch").oninput = load;
  document.getElementById("videoSort").onchange = load;
  document.getElementById("uploadButton").onclick = async () => {
    const file = document.getElementById("videoFile").files[0];
    if (!file) return toast("Select an MP4 file", true);
    const form = new FormData(); form.append("video",file);
    try {
      const result = await api("/api/videos/upload",{method:"POST",body:form});
      document.getElementById("uploadModal").classList.remove("open");
      toast(result.warning ? `Uploaded with warning: ${result.warning}` : "Video uploaded");
      load();
    } catch(error) { toast(error.message,true); }
  };
  load();
}

async function renderDestinations() {
  document.getElementById("pageTitle").textContent = "RTMP Destinations";
  content.innerHTML = `<div class="toolbar"><h2 style="margin:0">Destinations</h2><button class="primary" id="newDestination">Add Destination</button></div>
  <div class="card"><table><thead><tr><th>Name</th><th>Platform</th><th>Server URL</th><th>Stream Key</th><th>Status</th><th></th></tr></thead><tbody id="destinationRows"></tbody></table></div>
  <div class="modal" id="destinationModal"><div class="modal-box"><div class="modal-head"><h3 id="destinationTitle">Add Destination</h3><button class="close" data-close>×</button></div>
    <div class="form-grid"><label>Name<input id="destinationName"></label><label>Platform<select id="destinationPlatform"><option>YouTube Live</option><option>Facebook Live</option><option>Custom RTMP</option></select></label><label>RTMP/RTMPS server URL<input id="destinationUrl" placeholder="rtmp://server/live"></label><label>Stream key<input id="destinationKey" type="password" placeholder="Enter stream key"></label></div>
    <button class="primary" id="saveDestination" style="margin-top:14px;width:100%">Save Destination</button></div></div>`;
  let editingId=null;
  const modal=document.getElementById("destinationModal");
  document.querySelector("[data-close]").onclick=()=>modal.classList.remove("open");
  document.getElementById("newDestination").onclick=()=>{editingId=null;document.getElementById("destinationTitle").textContent="Add Destination";document.getElementById("destinationName").value="";document.getElementById("destinationUrl").value="";document.getElementById("destinationKey").value="";modal.classList.add("open");};
  async function load(){
    const rows=await api("/api/destinations");
    document.getElementById("destinationRows").innerHTML=rows.map(r=>`<tr><td>${escapeHtml(r.name)}</td><td>${escapeHtml(r.platform)}</td><td style="max-width:260px;overflow:hidden;text-overflow:ellipsis">${escapeHtml(r.server_url)}</td><td>${escapeHtml(r.stream_key_masked)}</td><td>${r.enabled?"Enabled":"Disabled"}</td><td><button class="secondary" data-edit="${r.id}">Edit</button> <button class="danger" data-delete="${r.id}">Delete</button></td></tr>`).join("")||'<tr><td colspan="6" style="color:var(--muted)">No destinations configured</td></tr>';
    document.querySelectorAll("[data-edit]").forEach(b=>b.onclick=()=>{editingId=Number(b.dataset.edit);const r=rows.find(x=>x.id===editingId);document.getElementById("destinationTitle").textContent="Edit Destination";document.getElementById("destinationName").value=r.name;document.getElementById("destinationPlatform").value=r.platform;document.getElementById("destinationUrl").value=r.server_url;document.getElementById("destinationKey").value="";modal.classList.add("open");});
    document.querySelectorAll("[data-delete]").forEach(b=>b.onclick=async()=>{if(confirm("Delete this destination?")){await api(`/api/destinations/${b.dataset.delete}`,{method:"DELETE"});toast("Destination deleted");load();}});
  }
  document.getElementById("saveDestination").onclick=async()=>{
    const body={name:document.getElementById("destinationName").value,platform:document.getElementById("destinationPlatform").value,server_url:document.getElementById("destinationUrl").value,stream_key:document.getElementById("destinationKey").value,enabled:true};
    try{await api(editingId?`/api/destinations/${editingId}`:"/api/destinations",{method:editingId?"PUT":"POST",body:JSON.stringify(body)});modal.classList.remove("open");toast("Destination saved");load();}catch(error){toast(error.message,true);}
  };
  load();
}

async function renderStreaming() {
  document.getElementById("pageTitle").textContent="Live Streaming";
  content.innerHTML=`<div class="grid stats" id="streamStats"></div><div class="grid" style="grid-template-columns:2fr 1fr;margin-top:16px">
    <div class="card"><h3>Streaming Configuration</h3><div class="form-grid"><label>Playlist<select id="streamPlaylist"></select></label><label>Destination<select id="streamDestination"></select></label><label>Orientation<select id="streamOrientation"><option value="landscape_1080">Landscape 1920×1080</option><option value="landscape_720">Landscape 1280×720</option><option value="portrait_1080">Portrait 1080×1920</option><option value="portrait_720">Portrait 720×1280</option></select></label><label>Playback mode<div id="streamMode" style="padding:10px 0;color:var(--muted)">Repeat entire playlist</div></label></div>
      <div style="display:flex;gap:8px;margin-top:16px;flex-wrap:wrap"><button class="primary" id="startStream">Start Live</button><button class="danger" id="stopStream">Stop Live</button><button class="secondary" id="restartStream">Restart</button><button class="secondary" id="refreshStatus">Refresh Status</button></div></div>
    <div class="card"><h3>Process Status</h3><div id="processStatus"></div></div></div>`;
  async function loadOptions(){
    const [playlists,destinations,settings]=await Promise.all([api("/api/playlists"),api("/api/destinations"),api("/api/settings")]);
    document.getElementById("streamPlaylist").innerHTML=playlists.map(p=>`<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
    document.getElementById("streamDestination").innerHTML=destinations.filter(d=>d.enabled).map(d=>`<option value="${d.id}">${escapeHtml(d.name)} (${escapeHtml(d.platform)})</option>`).join("");
    if(settings.default_orientation)document.getElementById("streamOrientation").value=settings.default_orientation;
    if(settings.default_playlist)document.getElementById("streamPlaylist").value=settings.default_playlist;
    if(settings.default_destination)document.getElementById("streamDestination").value=settings.default_destination;
  }
  async function refresh(){
    const [dashboard,logs]=await Promise.all([api("/api/dashboard"),api("/api/logs")]);
    const running=dashboard.process_running;
    document.getElementById("streamStats").innerHTML=stat("Application","Running","Dashboard service")+stat("FFmpeg Process",running?"Running":"Stopped","Actual process state")+stat("RTMP Connection","Unknown","Requires production probe")+stat("Platform Broadcast","Not detected","Local state cannot verify platform");
    document.querySelectorAll(".live-indicator i")[0].style.background=running?"var(--success)":"var(--muted)";
    document.getElementById("processStatus").innerHTML=`<p><span class="status-dot ${running?"running":""}"></span>${running?(dashboard.mode==="DEMO"?"DEMO process running":"FFmpeg process running"):"Stopped"}</p>
      <div class="stat-label">Uptime</div><div style="font-size:20px;margin:5px 0 14px">${formatUptime(dashboard.uptime||0)}</div>
      <div class="stat-label">Recent error</div><div style="margin-top:5px">${escapeHtml(dashboard.last_error||"None")}</div>
      ${dashboard.mode==="DEMO"?' <div class="alert" style="margin-top:14px;color:#b6c4e8;background:rgba(77,124,255,.08)">DEMO: no public platform broadcast.</div>':""}
      <div style="max-height:180px;overflow:auto;margin-top:14px">${logs.slice(0,8).map(l=>`<div style="font-size:11px;margin-bottom:7px;color:var(--muted)">${escapeHtml(l.created_at)} · ${escapeHtml(l.message)}</div>`).join("")}</div>`;
  }
  async function start(){const pid=document.getElementById("streamPlaylist").value,did=document.getElementById("streamDestination").value;if(!pid||!did)return toast("Select a playlist and destination",true);try{await api("/api/stream/start",{method:"POST",body:JSON.stringify({playlist_id:Number(pid),destination_id:Number(did),orientation:document.getElementById("streamOrientation").value})});toast("Stream start requested");refresh();}catch(error){toast(error.message,true);}}
  window.stopStream=async()=>{
    if(!confirm("Stop the active live stream?"))return;
    try{await api("/api/stream/stop",{method:"POST",body:"{}"});toast("Stream stopped");refresh();}catch(error){toast(error.message,true);}
  };
  window.restartStream=async()=>{try{await api("/api/stream/restart",{method:"POST",body:JSON.stringify({playlist_id:Number(document.getElementById("streamPlaylist").value),destination_id:Number(document.getElementById("streamDestination").value),orientation:document.getElementById("streamOrientation").value})});toast("Stream restart requested");refresh();}catch(error){toast(error.message,true);}};
  document.getElementById("startStream").onclick=start;document.getElementById("stopStream").onclick=window.stopStream;document.getElementById("restartStream").onclick=window.restartStream;document.getElementById("refreshStatus").onclick=refresh;
  await loadOptions();await refresh();
}

async function renderHistory(){
  document.getElementById("pageTitle").textContent="Stream History";
  content.innerHTML=`<div class="toolbar"><h2 style="margin:0">Stream History</h2><input id="historySearch" placeholder="Search history"></div><div class="card"><table><thead><tr><th>Started</th><th>Stopped</th><th>Duration</th><th>Playlist</th><th>Destination</th><th>Result</th><th>Error</th></tr></thead><tbody id="historyRows"></tbody></table></div>`;
  async function load(){const rows=await api(`/api/history?search=${encodeURIComponent(document.getElementById("historySearch").value)}`);document.getElementById("historyRows").innerHTML=rows.map(r=>`<tr><td>${escapeHtml(r.started_at||"-")}</td><td>${escapeHtml(r.stopped_at||"-")}</td><td>${formatDuration(r.duration)}</td><td>${escapeHtml(r.playlist_name||"-")}</td><td>${escapeHtml(r.destination_name||"-")}</td><td>${escapeHtml(r.result||"-")}</td><td>${escapeHtml(r.error||"")}</td></tr>`).join("")||'<tr><td colspan="7" style="color:var(--muted)">No stream sessions</td></tr>';};document.getElementById("historySearch").oninput=load;load();
}

async function renderSettings(){
  document.getElementById("pageTitle").textContent="Settings";
  content.innerHTML=`<div class="card" style="max-width:800px"><h3>Application Settings</h3><div class="form-grid" id="settingsGrid"></div><button class="primary" id="saveSettings" style="margin-top:16px">Save Settings</button></div>`;
  const settings=await api("/api/settings");
  const fields={
    application_name:["Application name","text"],default_orientation:["Default orientation","select"],default_playback_mode:["Default playback mode","select"],default_playlist:["Default playlist","text"],default_destination:["Default destination","text"],automatic_reconnect:["Automatic reconnect","select"],maximum_retries:["Maximum retry count","number"],log_retention:["Log retention (days)","number"],upload_size_limit:["Upload size limit (MB)","number"]
  };
  const grid=document.getElementById("settingsGrid");
  grid.innerHTML=Object.entries(fields).map(([key,[label,type]])=>{
    let input=`<input id="setting_${key}" type="${type}" value="${escapeHtml(settings[key]||"")}">`;
    if(type==="select"&&key==="default_orientation")input=`<select id="setting_${key}"><option value="landscape_1080" ${settings[key]==="landscape_1080"?"selected":""}>Landscape 1920×1080</option><option value="landscape_720" ${settings[key]==="landscape_720"?"selected":""}>Landscape 1280×720</option><option value="portrait_1080" ${settings[key]==="portrait_1080"?"selected":""}>Portrait 1080×1920</option><option value="portrait_720" ${settings[key]==="portrait_720"?"selected":""}>Portrait 720×1280</option></select>`;
    if(type==="select"&&key==="default_playback_mode")input=`<select id="setting_${key}"><option value="repeat_playlist" ${settings[key]==="repeat_playlist"?"selected":""}>Repeat entire playlist</option><option value="repeat_video">Repeat current video</option><option value="play_once">Play once</option></select>`;
    if(type==="select"&&key==="automatic_reconnect")input=`<select id="setting_${key}"><option value="true" ${settings[key]==="true"?"selected":""}>Enabled</option><option value="false" ${settings[key]==="false"?"selected":""}>Disabled</option></select>`;
    return `<label>${label}${input}</label>`;
  }).join("");
  document.getElementById("saveSettings").onclick=async()=>{const body={};for(const key of Object.keys(fields))body[key]=document.getElementById(`setting_${key}`).value;await api("/api/settings",{method:"PUT",body:JSON.stringify(body)});toast("Settings saved");};
}

async function renderSystem(){
  document.getElementById("pageTitle").textContent="System Status";
  content.innerHTML=`<div class="grid stats" id="systemStats"></div><div class="grid" style="grid-template-columns:1fr 1fr;margin-top:16px"><div class="card"><h3>Stream Engine</h3><div id="engineInfo"></div></div><div class="card"><h3>Recent Logs</h3><div id="recentLogs" style="max-height:300px;overflow:auto"></div></div></div>`;
  const [system,logs]=await Promise.all([api("/api/system"),api("/api/logs")]);
  document.getElementById("systemStats").innerHTML=stat("CPU",`${system.cpu_percent.toFixed(1)}%`,`Server usage`)+stat("RAM",`${system.ram_percent.toFixed(1)}%`,`${system.ram_available_mb} MB available`)+stat("Free Storage",formatBytes(system.disk_free_mb*1024*1024),"Available")+stat("Network",system.network_status,"Local status");
  document.getElementById("engineInfo").innerHTML=`${info("Mode",system.stream.mode)}${info("Application","Running")}${info("FFmpeg Process",system.stream.process_running?"Running":"Stopped")}<div style="margin-top:12px">${escapeHtml(system.stream.status)}</div>`;
  document.getElementById("recentLogs").innerHTML=logs.map(l=>`<div style="border-bottom:1px solid var(--border);padding:8px 0;font-size:12px"><strong>${escapeHtml(l.level)}</strong> · ${escapeHtml(l.created_at)}<br><span style="color:var(--muted)">${escapeHtml(l.message)}</span></div>`).join("")||'<div class="stat-label">No log entries</div>';
}

async function route(){
  document.querySelectorAll(".sidebar nav a").forEach(a=>a.classList.toggle("active",a.dataset.page===content.dataset.page));
  sidebar.classList.remove("open");
  refreshTopStatus();
  try{
    switch(content.dataset.page){
      case "video_library": await renderVideos();break;
      case "playlists": await renderPlaylists();break;
      case "streaming": await renderStreaming();break;
      case "destinations": await renderDestinations();break;
      case "history": await renderHistory();break;
      case "settings": await renderSettings();break;
      case "system": await renderSystem();break;
      default: await renderDashboard();
    }
  }catch(error){toast(error.message,true);content.innerHTML=`<div class="card"><h3>Unable to load</h3><p style="color:var(--muted)">${escapeHtml(error.message)}</p></div>`;}
}

route();

async function renderPlaylists() {
  document.getElementById("pageTitle").textContent = "Playlist Manager";
  content.innerHTML = `<div class="toolbar"><h2 style="margin:0">Playlists</h2><button class="primary" id="newPlaylist">Create Playlist</button></div><div id="playlistGrid" class="grid" style="grid-template-columns:repeat(2,minmax(0,1fr))"></div>
  <div class="modal" id="playlistModal"><div class="modal-box"><div class="modal-head"><h3 id="playlistModalTitle">Create Playlist</h3><button class="close" data-close>×</button></div>
    <div class="form-grid"><label>Name<input id="playlistName"></label><label>Playback<select id="playlistMode"><option value="repeat_playlist">Repeat entire playlist</option><option value="repeat_video">Repeat current video</option><option value="play_once">Play once</option></select></label></div>
    <button class="primary" id="savePlaylist" style="margin-top:14px">Save</button></div></div>
  <div class="modal" id="itemsModal"><div class="modal-box"><div class="modal-head"><h3>Edit Videos</h3><button class="close" data-items-close>×</button></div><div id="availableVideos"></div><button class="primary" id="saveItems" style="margin-top:12px">Save Order</button></div></div>`;
  let editingId = null;
  const modal = document.getElementById("playlistModal");
  document.querySelector("[data-close]").onclick = () => modal.classList.remove("open");
  document.getElementById("newPlaylist").onclick = () => { editingId=null; document.getElementById("playlistModalTitle").textContent="Create Playlist"; document.getElementById("playlistName").value=""; document.getElementById("playlistMode").value="repeat_playlist"; modal.classList.add("open"); };
  document.getElementById("savePlaylist").onclick = async () => {
    const body = {name:document.getElementById("playlistName").value, playback_mode:document.getElementById("playlistMode").value};
    try {
      await api(editingId ? `/api/playlists/${editingId}` : "/api/playlists",{method:editingId?"PUT":"POST",body:JSON.stringify(body)});
      modal.classList.remove("open"); toast("Playlist saved"); load();
    } catch(error){toast(error.message,true);}
  };
  async function load() {
    const [playlists,videos] = await Promise.all([api("/api/playlists"),api("/api/videos")]);
    document.getElementById("playlistGrid").innerHTML = playlists.map(p => `<div class="card"><div style="display:flex;justify-content:space-between"><div><h3>${escapeHtml(p.name)}</h3><div class="stat-label">${p.items.length} videos · ${formatDuration(p.duration)}</div></div><div><button class="secondary" data-edit="${p.id}">Rename</button> <button class="danger" data-delete="${p.id}">Delete</button></div></div>
      <div class="playlist-list" style="margin-top:12px">${p.items.map(i=>`<div class="playlist-item"><span>${escapeHtml(i.original_name)}</span><span>${formatDuration(i.duration)}</span></div>`).join("") || '<div class="stat-label">No videos</div>'}</div>
      <button class="primary" data-items="${p.id}" style="margin-top:12px">Add / Reorder Videos</button></div>`).join("") || '<div class="card">No playlists yet</div>';
    document.querySelectorAll("[data-edit]").forEach(b=>b.onclick=async()=>{editingId=Number(b.dataset.edit);const p=playlists.find(x=>x.id===editingId);document.getElementById("playlistModalTitle").textContent="Rename Playlist";document.getElementById("playlistName").value=p.name;document.getElementById("playlistMode").value=p.playback_mode;modal.classList.add("open");});
    document.querySelectorAll("[data-delete]").forEach(b=>b.onclick=async()=>{if(confirm("Delete this playlist?")){await api(`/api/playlists/${b.dataset.delete}`,{method:"DELETE"});toast("Playlist deleted");load();}});
    document.querySelectorAll("[data-items]").forEach(b=>b.onclick=()=>openItems(Number(b.dataset.items),playlists.find(p=>p.id===Number(b.dataset.items)),videos));
  }
  function openItems(id,playlist,videos) {
    const modalItems=document.getElementById("itemsModal");modalItems.classList.add("open");
    let selected=playlist.items.map(i=>i.id);
    const list=document.getElementById("availableVideos");
    function draw(){
      list.innerHTML=selected.map((id,index)=>{const v=videos.find(x=>x.id===id);return v?`<div class="playlist-item"><span>${index+1}. ${escapeHtml(v.original_name)}</span><span><button class="secondary" data-up="${index}" ${index===0?"disabled":""}>↑</button> <button class="secondary" data-down="${index}" ${index===selected.length-1?"disabled":""}>↓</button> <button class="danger" data-remove="${index}">Remove</button></span></div>`:"";}).join("")+
        `<select id="videoToAdd" style="width:100%;margin-top:12px"><option value="">Add uploaded video...</option>${videos.filter(v=>!selected.includes(v.id)).map(v=>`<option value="${v.id}">${escapeHtml(v.original_name)}</option>`).join("")}</select>`;
      list.querySelectorAll("[data-up]").forEach(b=>b.onclick=()=>{const i=Number(b.dataset.up);[selected[i-1],selected[i]]=[selected[i],selected[i-1]];draw();});
      list.querySelectorAll("[data-down]").forEach(b=>b.onclick=()=>{const i=Number(b.dataset.down);[selected[i],selected[i+1]]=[selected[i+1],selected[i]];draw();});
      list.querySelectorAll("[data-remove]").forEach(b=>b.onclick=()=>{selected.splice(Number(b.dataset.remove),1);draw();});
      list.querySelector("#videoToAdd").onchange=e=>{if(e.target.value){selected.push(Number(e.target.value));draw();}};
    }
    draw();
    document.getElementById("saveItems").onclick=async()=>{await api(`/api/playlists/${id}/items`,{method:"PUT",body:JSON.stringify({video_ids:selected})});modalItems.classList.remove("open");toast("Playlist items saved");load();};
  }
  document.querySelector("[data-items-close]").onclick=()=>document.getElementById("itemsModal").classList.remove("open");
  load();
}
