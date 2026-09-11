(function(){var dragged=null;
document.addEventListener('dragstart',function(e){var li=e.target.closest&&e.target.closest('.titem');if(li){dragged=li;e.dataTransfer.effectAllowed='move';}});
document.addEventListener('dragover',function(e){if(!dragged)return;var ul=e.target.closest('.tasklist');if(!ul)return;e.preventDefault();var li=e.target.closest('.titem');if(li&&li!==dragged){var r=li.getBoundingClientRect();ul.insertBefore(dragged,(e.clientY-r.top)/r.height>0.5?li.nextSibling:li);}else if(!li){ul.appendChild(dragged);}});
document.addEventListener('drop',function(e){if(!dragged)return;e.preventDefault();dragged=null;
var blocks=[].map.call(document.querySelectorAll('.block'),function(b){return {id:b.getAttribute('data-block-id'),tasks:[].map.call(b.querySelectorAll('.titem'),function(li){return li.getAttribute('data-ref');})};});
fetch('/web/catalog/layout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({blocks:blocks})}).then(function(){location.reload();});});
})();
