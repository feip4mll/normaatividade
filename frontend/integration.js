/* Checkout real por HTTP; dinheiro e produtos continuam fictícios. */
let pendingKey=null, pendingPayload=null, statusTimer=null;
const escapeText=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
document.addEventListener('click',async e=>{
  const button=e.target.closest('[data-action="pay"]');
  if(!button)return;
  e.stopImmediatePropagation();
  if(busy)return;
  const payload=JSON.stringify({items:items().map(p=>({id:p.id,quantity:cart[p.id]})),method,outcome:document.querySelector('#outcome').value});
  if(pendingPayload!==payload){pendingKey=crypto.randomUUID();pendingPayload=payload}
  busy=true;button.disabled=true;button.textContent='Enviando pedido…';
  document.querySelectorAll('[data-method],#outcome,#installments').forEach(x=>x.disabled=true);
  try{
    const start=performance.now();
    const response=await fetch('/api/orders',{method:'POST',headers:{'Content-Type':'application/json','Idempotency-Key':pendingKey},body:payload});
    const result=await response.json();
    if(!response.ok)throw new Error(result.error||'Falha no envio');
    order={id:result.order_id,total:result.total_cents/100,method,latency:Math.round(performance.now()-start)};
    sessionStorage.setItem('norma-last-order',JSON.stringify(order));
    pendingKey=null;pendingPayload=null;cart={};save();delivery=null;location.hash='confirmacao';
  }catch(error){if(location.hash==='#pagamento'){payment();document.querySelector('#payment-error').textContent=error.message+' A sacola foi preservada.'}}
  finally{busy=false}
},true);
success=function(){
  if(!order){try{order=JSON.parse(sessionStorage.getItem('norma-last-order'))}catch{}}
  if(!order){location.hash='home';return}
  app.innerHTML=`<section class="success fade"><div class="seal">◷</div><small>NORMA · COMPRA DE DEMONSTRAÇÃO</small><h2 id="order-status">Pedido recebido.<br>Em processamento.</h2><p>A API recebeu o pedido e publicou o evento no RabbitMQ.<br>Os serviços processam a compra de forma independente.</p><div class="notice">HTTP 202 · Resposta em ${order.latency} ms · Sem aguardar os workers</div><div class="panel"><div class="line"><span>Pedido</span><b style="font-size:12px;overflow-wrap:anywhere">${escapeText(order.id)}</b></div><div class="line total"><span>Total</span><b>${money(order.total)}</b></div><div id="event-history" class="muted">Aguardando eventos…</div></div><a class="btn" href="#colecao">Voltar à loja</a> <a class="btn outline" href="demo.html">Painel da atividade</a><p class="muted">Não há cobrança nem envio real de produtos.</p></section>`;
  clearTimeout(statusTimer);
  const update=async()=>{if(location.hash!=='#confirmacao')return;try{const response=await fetch('/api/orders/'+encodeURIComponent(order.id));if(!response.ok)throw new Error('Falha na consulta');let data=await response.json();document.querySelector('#order-status').textContent=({recebido:'Pedido recebido. Em processamento.',pago:'Pagamento aprovado. Reservando estoque.',concluido:'Pedido concluído. Estoque reservado.',recusado:'Pagamento recusado. Mensagem enviada à DLQ.'})[data.status]||data.status;document.querySelector('#event-history').innerHTML=data.history.map(h=>`<p style="margin:12px 0"><strong>${escapeText(h.event)}</strong><br>${escapeText(h.worker)} · ${new Date(h.created*1000).toLocaleTimeString('pt-BR')}</p>`).join('')}catch{const h=document.querySelector('#event-history');if(h)h.textContent='Conexão interrompida. Tentando novamente…'}statusTimer=setTimeout(update,1500)};
  update();
};
document.querySelector('footer').insertAdjacentHTML('beforeend','<a href="demo.html" style="font-size:13px;text-decoration:underline">Laboratório EDA</a>');
if(location.hash==='#confirmacao')success();
