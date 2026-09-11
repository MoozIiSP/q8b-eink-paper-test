const $ = id => document.getElementById(id);
let draft = null, connected = false, working = false, state = null, previewURL = null;
const names = {idle:'空闲', starting:'准备刷新', reset:'复位', writing:'传输画面', 'power on':'开启高压', refresh:'面板刷新', 'power off':'关闭高压', sleep:'深睡眠', done:'已完成', failed:'失败', interrupted:'上次刷新中断'};
function message(text){$('message').textContent=text;}
function buttons(){
  $('refresh').disabled = !connected || !draft || working || !state || state.active || state.wait_seconds > 0;
  for (const id of ['bars','white']) $(id).disabled = working || !connected;
  $('prepare').querySelector('button').disabled = working || !connected;
}
async function api(url, options={}){
  const response = await fetch(url,options);
  if(!response.ok){const error=await response.json();throw new Error(error.error || '请求失败');}
  return response;
}
async function status(){
  try {state=await (await api('/api/status')).json();connected=true;
    $('mode').textContent=state.simulate?'模拟模式 · 不操作 GPIO':'Q8B · 硬件模式';
    $('stage').textContent=names[state.stage] || state.stage;
    $('wait').textContent=state.active?'任务执行中':state.wait_seconds ? `${state.wait_seconds} 秒后`:'现在';
    $('device-error').textContent=state.error || '';
  } catch(error){connected=false;$('mode').textContent='未连接';$('stage').textContent='状态不可用';$('wait').textContent='—';message(error.message);}
  buttons();
}
async function prepare(kind){
  if(working)return;
  if(kind==='image' && !$('file').files[0]){message('请先选择图片。');return;}
  working=true;draft=null;buttons();message('正在处理图片…');
  const body=new FormData();body.append('kind',kind);
  if(kind==='image'){body.append('image',$('file').files[0]);body.append('algorithm',$('algorithm').value);body.append('fit',$('fit').value);}
  try {const result=await (await api('/api/prepare',{method:'POST',body})).json();
    const blob=await (await api('/api/preview/'+result.id)).blob();
    if(previewURL)URL.revokeObjectURL(previewURL);previewURL=URL.createObjectURL(blob);
    $('preview').src=previewURL;$('preview').hidden=false;$('empty').hidden=true;draft=result.id;
    message('预览已生成。确认画面后点击刷新。');
  }catch(error){message(error.message);}finally{working=false;buttons();}
}
$('prepare').onsubmit=event=>{event.preventDefault();prepare('image');};
$('bars').onclick=()=>prepare('bars');$('white').onclick=()=>prepare('white');
$('refresh').onclick=async()=>{
  working=true;buttons();
  try{const result=await (await api('/api/refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:draft,force:$('force').checked})})).json();
    message(result.result==='unchanged'?'画面未变化，已跳过刷新。':'刷新任务已提交，请查看设备状态。');await status();
  }catch(error){message(error.message);}finally{working=false;buttons();}
};
buttons();status();setInterval(status,2000);
