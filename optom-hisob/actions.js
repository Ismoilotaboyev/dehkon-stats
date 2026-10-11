import {Q,n,body,go,audit} from './core.js';
const validImage=f=>f&&(/^image\//i.test(f.mime)||/\.(jpg|jpeg|png|webp|heic)$/i.test(f.filename));
const validAudio=f=>f&&(/^audio\//i.test(f.mime)||/\.(m4a|mp3|wav|aac|ogg|webm)$/i.test(f.filename));
const ret=(b,fallback='/')=>{let x=String(b.returnTo||'');return x.startsWith('/')&&!x.startsWith('//')?x:fallback};
const loadSnap=x=>({name:x.name,product:x.product,arrived_kg:n(x.arrived_kg),arrived_bags:n(x.arrived_bags),purchase_amount:n(x.purchase_amount),profit_mode:x.profit_mode,commission_per_kg:n(x.commission_per_kg)});
const saleSnap=x=>({customer_id:x.customer_id?+x.customer_id:null,kg:n(x.kg),bags:n(x.bags),price_per_kg:n(x.price_per_kg),total:n(x.total),paid_amount:n(x.paid_amount),debt_amount:n(x.debt_amount)});
const customerSnap=x=>({name:x.name,phone:x.phone||'',place:x.place||'',opening_debt:n(x.opening_debt)});
const paymentSnap=x=>({customer_id:+x.customer_id,sale_id:x.sale_id?+x.sale_id:null,amount:n(x.amount),note:x.note||''});
const expenseSnap=x=>({load_id:x.load_id?+x.load_id:null,name:x.name,amount:n(x.amount),note:x.note||''});
const paymentSplit=(mode,total,raw)=>{if(mode==='debt')return{paid:0,debt:total};if(mode==='partial'){let paid=Math.max(0,Math.min(total,n(raw)));return{paid,debt:Math.max(0,total-paid)}}return{paid:total,debt:0}};
export async function actions(r,res,url,u){let b=await body(r),p=url.pathname;
 if(p==='/action/load'){let s=u.role==='manager'?+b.sellerId:u.id;if(s){let mode=b.profitMode==='commission'?'commission':'own',buy=mode==='own'?n(b.buy):0,commission=mode==='commission'?n(b.commissionPerKg):0;await Q(`INSERT INTO loads(seller_id,name,product,arrived_kg,arrived_bags,purchase_amount,profit_mode,commission_per_kg) VALUES($1,$2,$3,$4,$5,$6,$7,$8)`,[s,b.name||'',b.product||'Kartoshka',n(b.kg),n(b.bags),buy,mode,commission])}return go(res,'/loads')}
 if(p==='/action/customer'){let s=u.role==='manager'?+b.sellerId:u.id;if(s)await Q(`INSERT INTO customers(seller_id,name,phone,place,opening_debt) VALUES($1,$2,$3,$4,$5)`,[s,b.name||'',b.phone||'',b.place||'',n(b.debt)]);return go(res,'/customers')}
 if(p==='/action/sale'){
  let L=(await Q(`SELECT * FROM loads WHERE id=$1`,[+b.loadId]))[0];if(!L||(u.role!=='manager'&&L.seller_id!==u.id))return go(res,'/sales');
  let sold=(await Q(`SELECT COALESCE(SUM(kg),0) s FROM sales WHERE load_id=$1`,[L.id]))[0],kg=n(b.kg);if(kg<=0||n(sold.s)+kg>n(L.arrived_kg))return go(res,`/load/${L.id}`);
  let price=n(b.price),total=kg*price,split=paymentSplit(String(b.paymentMode||'cash'),total,b.paid),cid=null;
  if(b.customerId){let C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.customerId]))[0];if(C?.seller_id===L.seller_id)cid=C.id}
  if(split.debt>0&&!cid)return go(res,`/load/${L.id}?error=customer`);
  let files=b.__files||{},image=validImage(files.image)?files.image:null,audio=validAudio(files.audio)?files.audio:null;
  let sale=(await Q(`INSERT INTO sales(seller_id,load_id,customer_id,kg,bags,price_per_kg,total,paid_amount,debt_amount) VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id`,[L.seller_id,L.id,cid,kg,n(b.bags),price,total,split.paid,split.debt]))[0];
  if(sale&&(image||audio))await Q(`INSERT INTO sale_attachments(sale_id,image_data,image_mime,audio_data,audio_mime) VALUES($1,$2,$3,$4,$5)`,[sale.id,image?.data||null,image?.mime||null,audio?.data||null,audio?.mime||null]);return go(res,`/load/${L.id}`)
 }
 if(p==='/action/payment'){
  let C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.customerId]))[0];if(!C||(u.role!=='manager'&&C.seller_id!==u.id))return go(res,'/debts');
  let saleId=b.saleId?+b.saleId:null,amount=Math.max(0,n(b.amount));if(amount<=0)return go(res,'/debts');
  if(saleId){let S=(await Q(`SELECT s.*,GREATEST(s.debt_amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.sale_id=s.id),0),0) remaining FROM sales s WHERE s.id=$1`,[saleId]))[0];if(!S||S.seller_id!==C.seller_id||S.customer_id!==C.id)return go(res,'/debts');amount=Math.min(amount,n(S.remaining));if(amount<=0)return go(res,'/debts')}
  else{let D=(await Q(`SELECT GREATEST(c.opening_debt-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id AND p.sale_id IS NULL),0),0) debt FROM customers c WHERE c.id=$1`,[C.id]))[0];amount=Math.min(amount,n(D?.debt));if(amount<=0)return go(res,'/debts')}
  await Q(`INSERT INTO payments(seller_id,customer_id,sale_id,amount,note) VALUES($1,$2,$3,$4,$5)`,[C.seller_id,C.id,saleId,amount,b.note||'']);return go(res,'/debts')
 }
 if(p==='/action/expense'){let s=u.role==='manager'?+b.sellerId:u.id,lid=null;if(b.loadId){let L=(await Q(`SELECT * FROM loads WHERE id=$1`,[+b.loadId]))[0];if(L&&(u.role==='manager'||L.seller_id===u.id)){s=L.seller_id;lid=L.id}}if(s)await Q(`INSERT INTO expenses(seller_id,load_id,name,amount,note) VALUES($1,$2,$3,$4,$5)`,[s,lid,b.name||'',n(b.amount),b.note||'']);return go(res,lid?`/load/${lid}`:'/expenses')}
 if(p==='/action/edit-load'){
  let L=(await Q(`SELECT * FROM loads WHERE id=$1`,[+b.id]))[0];if(!L||(u.role!=='manager'&&L.seller_id!==u.id))return go(res,'/loads');
  let sums=(await Q(`SELECT COALESCE(SUM(kg),0) kg,COALESCE(SUM(bags),0) bags FROM sales WHERE load_id=$1`,[L.id]))[0],kg=n(b.kg),bags=n(b.bags);if(kg<n(sums.kg)||bags<n(sums.bags))return go(res,ret(b,`/load/${L.id}`));
  let mode=b.profitMode==='commission'?'commission':'own',after={name:String(b.name||''),product:String(b.product||'Kartoshka'),arrived_kg:kg,arrived_bags:bags,purchase_amount:mode==='own'?n(b.buy):0,profit_mode:mode,commission_per_kg:mode==='commission'?n(b.commissionPerKg):0},before=loadSnap(L);
  await Q(`UPDATE loads SET name=$1,product=$2,arrived_kg=$3,arrived_bags=$4,purchase_amount=$5,profit_mode=$6,commission_per_kg=$7 WHERE id=$8`,[after.name,after.product,after.arrived_kg,after.arrived_bags,after.purchase_amount,after.profit_mode,after.commission_per_kg,L.id]);await audit(u,'load',L.id,before,after);return go(res,ret(b,`/load/${L.id}`));
 }
 if(p==='/action/edit-sale'){
  let S=(await Q(`SELECT * FROM sales WHERE id=$1`,[+b.id]))[0];if(!S||(u.role!=='manager'&&S.seller_id!==u.id))return go(res,'/sales');let L=(await Q(`SELECT * FROM loads WHERE id=$1`,[S.load_id]))[0];
  let sold=(await Q(`SELECT COALESCE(SUM(kg),0) kg FROM sales WHERE load_id=$1 AND id<>$2`,[L.id,S.id]))[0],kg=n(b.kg);if(kg<=0||n(sold.kg)+kg>n(L.arrived_kg))return go(res,ret(b,`/load/${L.id}`));
  let cid=null;if(b.customerId){let C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.customerId]))[0];if(C?.seller_id===S.seller_id)cid=C.id;else return go(res,ret(b,`/load/${L.id}`))}
  let price=n(b.price),total=kg*price,split=paymentSplit(String(b.paymentMode||'cash'),total,b.paid),repaid=n((await Q(`SELECT COALESCE(SUM(amount),0) a FROM payments WHERE sale_id=$1`,[S.id]))[0]?.a);
  if(split.debt>0&&!cid)return go(res,ret(b,`/load/${L.id}`));if(split.debt<repaid)return go(res,ret(b,`/load/${L.id}`));
  let after={customer_id:cid,kg,bags:n(b.bags),price_per_kg:price,total,paid_amount:split.paid,debt_amount:split.debt},before=saleSnap(S);
  await Q(`UPDATE sales SET customer_id=$1,kg=$2,bags=$3,price_per_kg=$4,total=$5,paid_amount=$6,debt_amount=$7 WHERE id=$8`,[after.customer_id,after.kg,after.bags,after.price_per_kg,after.total,after.paid_amount,after.debt_amount,S.id]);await audit(u,'sale',S.id,before,after);return go(res,ret(b,`/load/${L.id}`));
 }
 if(p==='/action/edit-customer'){
  let C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.id]))[0];if(!C||(u.role!=='manager'&&C.seller_id!==u.id))return go(res,'/customers');let before=customerSnap(C),after={name:String(b.name||''),phone:String(b.phone||''),place:String(b.place||''),opening_debt:n(b.debt)};
  await Q(`UPDATE customers SET name=$1,phone=$2,place=$3,opening_debt=$4 WHERE id=$5`,[after.name,after.phone,after.place,after.opening_debt,C.id]);await audit(u,'customer',C.id,before,after);return go(res,ret(b,'/customers'));
 }
 if(p==='/action/edit-payment'){
  let P=(await Q(`SELECT * FROM payments WHERE id=$1`,[+b.id]))[0];if(!P||(u.role!=='manager'&&P.seller_id!==u.id))return go(res,'/debts');let before=paymentSnap(P),amount=Math.max(0,n(b.amount));
  if(P.sale_id){let S=(await Q(`SELECT s.*,GREATEST(s.debt_amount-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.sale_id=s.id AND p.id<>$2),0),0) max_amount FROM sales s WHERE s.id=$1`,[P.sale_id,P.id]))[0];if(!S||S.seller_id!==P.seller_id||amount>n(S.max_amount))return go(res,ret(b,'/debts'));let after={customer_id:P.customer_id,sale_id:P.sale_id,amount,note:String(b.note||'')};await Q(`UPDATE payments SET amount=$1,note=$2 WHERE id=$3`,[after.amount,after.note,P.id]);await audit(u,'payment',P.id,before,after);return go(res,ret(b,'/debts'))}
  let C=(await Q(`SELECT * FROM customers WHERE id=$1`,[+b.customerId]))[0];if(!C||C.seller_id!==P.seller_id)return go(res,ret(b,'/debts'));let M=(await Q(`SELECT GREATEST(c.opening_debt-COALESCE((SELECT SUM(p.amount) FROM payments p WHERE p.customer_id=c.id AND p.sale_id IS NULL AND p.id<>$2),0),0) max_amount FROM customers c WHERE c.id=$1`,[C.id,P.id]))[0];if(amount>n(M?.max_amount))return go(res,ret(b,'/debts'));let after={customer_id:C.id,sale_id:null,amount,note:String(b.note||'')};await Q(`UPDATE payments SET customer_id=$1,amount=$2,note=$3 WHERE id=$4`,[after.customer_id,after.amount,after.note,P.id]);await audit(u,'payment',P.id,before,after);return go(res,ret(b,'/debts'));
 }
 if(p==='/action/edit-expense'){
  let E=(await Q(`SELECT * FROM expenses WHERE id=$1`,[+b.id]))[0];if(!E||(u.role!=='manager'&&E.seller_id!==u.id))return go(res,'/expenses');let lid=null;if(b.loadId){let L=(await Q(`SELECT * FROM loads WHERE id=$1`,[+b.loadId]))[0];if(!L||L.seller_id!==E.seller_id)return go(res,ret(b,'/expenses'));lid=L.id}let before=expenseSnap(E),after={load_id:lid,name:String(b.name||''),amount:n(b.amount),note:String(b.note||'')};
  await Q(`UPDATE expenses SET load_id=$1,name=$2,amount=$3,note=$4 WHERE id=$5`,[after.load_id,after.name,after.amount,after.note,E.id]);await audit(u,'expense',E.id,before,after);return go(res,ret(b,E.load_id?`/load/${E.load_id}`:'/expenses'));
 }
 go(res,'/')}
