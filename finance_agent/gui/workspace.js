/* Existing services, owner commands and display acknowledgements; no browser authority. */
let workspaceGeneration = '';
function prepareRequest(value) { setView('chat'); $('message').value=value; $('message').focus(); }
function fillOptions(select, items, value) {
  select.replaceChildren();
  for (const item of items) { const option=el('option','',item.label); option.value=item.id; select.append(option); }
  if (items.some(item=>item.id===value)) select.value=value;
}
function updatePeriods() {
  const company=((S.settings||{}).companies||[]).find(c=>c.company_id===$('browse-company').value);
  const prior=$('browse-period').value;
  fillOptions($('browse-known-periods'),(company?.periods||[]).map(p=>({id:p,label:p})),prior);
  if(!prior)$('browse-period').value=company?.periods[0]||'';
}
function renderWorkspace() {
  if (!S) return;
  const settings=S.settings||{}, generation=(S.context||{}).generation+'|'+(S.session||{}).user+'|'+(S.session||{}).workbook;
  const changed=generation!==workspaceGeneration;
  const oldCompany=changed?'':$('browse-company').value;
  if(changed){$('browse-period').value='';$('browse-reference').value='';}
  fillOptions($('browse-company'),(settings.companies||[]).map(c=>({id:c.company_id,label:(c.name||c.company_name||c.company_id)+' · '+c.company_id})),oldCompany);
  updatePeriods();
  fillOptions($('binding-select'),(settings.bindings||[]).map(b=>({id:b.id,label:b.label+(b.current?'（当前）':'')})),
    (settings.bindings||[]).find(b=>b.current)?.id);
  fillOptions($('assistant-select'),(settings.assistants||[]).map(a=>({id:a.id,label:a.name})),settings.assistant_id);
  $('apply-assistant').disabled=!(settings.assistants||[]).length;
  $('personal-current').textContent='当前：'+(settings.personal_detail||'普通');
  if (!settings.model?.configured) $('mode').textContent='AI尚未配置 · 可浏览账簿，请在设置保存本机密钥';
  if (generation!==workspaceGeneration) { $('browse-table').replaceChildren(); $('browse-facts').textContent=''; workspaceGeneration=generation; }
  const workspace=S.workspace, result=workspace?.result;
  if (result) {
    $('browse-status').textContent=result.ok?'当前账簿实际读取结果 · '+(workspace.arguments.company_id||''):
      result.status==='NO_DATA'?'当前范围没有记录。':'读取未完成：'+(result.error||result.status);
    $('browse-facts').textContent=S.current_result?.cards||S.current_result?.text||'';
    let rows=Array.isArray(result.data)?result.data:result.data?.rows;
    if (!rows && result.data && typeof result.data==='object' && result.data.invoice_no) rows=[result.data];
    const box=$('browse-table');box.replaceChildren();
    if (rows?.length) {
      const names={company_id:'企业',invoice_no:'发票号码',invoice_date:'开票日期',seller_name:'销售方',item_name:'项目',
        amount:'金额（元）',purpose:'用途',remark:'备注',has_purpose:'用途状态',transaction_no:'流水编号',
        transaction_date:'交易日期',direction:'方向',counterparty_name:'交易对方',rule_id:'规则',version:'版本',name:'名称',preference_key:'偏好',value:'内容'};
      const keys=Object.keys(rows[0]).filter(k=>names[k]);
      if (keys.length) {
        const table=el('table','business-table'), head=el('tr');
        for (const k of keys)head.append(el('th','',names[k]));head.append(el('th','','继续办理'));table.append(head);
        for (const row of rows) {
          const tr=el('tr');for (const k of keys)tr.append(el('td','',row[k]===null||row[k]===''?'未填写':
            typeof row[k]==='boolean'?(row[k]?'已填写':'未填写'):String(row[k])));
          const cell=el('td');
          if(row.invoice_no){const b=el('button','btn small','查看 / 带入对话');b.onclick=async()=>{
            await act('/api/read_business',{name:'get_invoice',arguments:{company_id:row.company_id||workspace.arguments.company_id,invoice_no:row.invoice_no}});
            prepareRequest('请针对企业 '+(row.company_id||workspace.arguments.company_id)+' 的发票 '+row.invoice_no+' 继续办理：');
          };cell.append(b);}
          tr.append(cell);table.append(tr);
        }box.append(table);
      }
    }
    if(result.data?.total!==undefined)$('browse-status').textContent+=' · 共 '+result.data.total+' 张 · 第 '+(workspace.arguments.page||1)+' 页';
  }
  const records=$('records-list');records.replaceChildren();
  for(const turn of [...(S.turns||[])].reverse()) {
    const card=el('section','settings-card');card.append(el('h2','','第 '+turn.seq+' 轮 · '+(turn.operation?.status||turn.state||'历史')));
    card.append(el('p','hint','当时记录；当前事实请重新查询。'));
    for(const message of turn.messages||[])card.append(el('p','workspace-facts',(message.role==='user'?'你：':'工作台：')+message.text));
    records.append(card);
  }
  if(!(S.turns||[]).length)records.append(el('p','hint','当前会话没有历史记录；可从左侧切换会话回看。'));
  if(window.chrome?.webview)window.chrome.webview.postMessage({kind:'ui-ready'});
}
async function browse(page=1) {
  if(busy)return;
  const name=$('browse-kind').value, company_id=$('browse-company').value;
  const [year,month]=$('browse-period').value.split('-').map(Number), reference=$('browse-reference').value.trim();
  if(!company_id){toast('请选择可读取的企业。',true);return;}
  if(!['get_invoice','list_rule_versions','list_materials'].includes(name)&&(!year||!month)){toast('请选择明确账期。',true);return;}
  let args={company_id,year,month};
  if(name==='list_invoice_directory')args={...args,page,sort_by:$('browse-sort').value,sort_order:'asc'};
  if(name==='get_invoice')args={company_id,invoice_no:reference};
  if(name==='list_bank_transactions'&&$('browse-direction').value)args.direction=$('browse-direction').value;
  if(name==='get_applicable_rules')args={company_id,rule_type:reference==='R001'?'amount':reference==='R004'?'bank':'purpose',business_date:year+'-'+String(month).padStart(2,'0')+'-01'};
  if(name==='list_rule_versions')args={company_id,rule_id:reference||'R002'};
  if(name==='list_materials')args={company_id};
  await act('/api/read_business',{name,arguments:args});
}
$('browse-company').addEventListener('change',updatePeriods);
$('browse-run').onclick=()=>browse();
$('browse-prev').onclick=()=>browse(Math.max(1,(S.workspace?.arguments.page||1)-1));
$('browse-next').onclick=()=>browse((S.workspace?.arguments.page||1)+1);
$('apply-binding').onclick=()=>act('/api/binding',{selector:$('binding-select').value});
$('import-book').onclick=async()=>{
  const file=$('workbook-file').files[0];if(!file){toast('请选择xlsx账簿。',true);return;}
  if(file.size>5000000){toast('账簿超过5MB。',true);return;}
  const reader=new FileReader();reader.onload=()=>act('/api/import_workbook',{name:file.name,content:String(reader.result).split(',')[1]});reader.readAsDataURL(file);
};
$('save-profile').onclick=async()=>{
  const api_key=$('edit-key').value;$('edit-key').value='';
  await act('/api/profile_save',{profile_name:$('edit-profile-name').value.trim(),provider:$('edit-provider').value,
    model:$('edit-model').value.trim(),base_url:$('edit-url').value.trim(),api_key});
};
$('profile-select').addEventListener('change',()=>{
  const p=(S.settings?.profiles||[]).find(p=>p.profile_name===$('profile-select').value);if(!p)return;
  $('edit-profile-name').value=p.profile_name;$('edit-provider').value=p.provider;$('edit-model').value=p.model;$('edit-url').value=p.base_url;
});
$('ask-preferences').onclick=()=>act('/api/read_business',{name:'manage_preference',arguments:{company_id:$('browse-company').value,action:'list'}});
$('apply-assistant').onclick=()=>act('/api/assistant',{identifier:$('assistant-select').value});
$('prepare-preference').onclick=()=>act('/api/preference',{company_id:$('browse-company').value,action:$('preference-action').value,key:$('preference-key').value.trim(),value:$('preference-value').value.trim()});
$('save-personal').onclick=()=>act('/api/preference',{scope:'personal',action:$('personal-detail').value==='普通'?'delete':'set',key:'阅读习惯',value:$('personal-detail').value==='普通'?'':$('personal-detail').value});
$('ask-material').onclick=()=>prepareRequest('请列出企业 '+$('browse-company').value+' 的可读业务资料，并让我选择原文来源。');
if(S)renderWorkspace();
