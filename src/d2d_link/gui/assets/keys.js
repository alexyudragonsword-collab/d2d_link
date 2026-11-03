// Enter / Space activate the page's clickable blocks (lane cells, scenario rows,
// field groups): Dash counts clicks, a keyboard user needs them to count too.
document.addEventListener('keydown', function (e) {
  var t = e.target;
  if ((e.key === 'Enter' || e.key === ' ') && t && t.getAttribute && t.getAttribute('role') === 'button'
      && t.tagName !== 'BUTTON' && t.tagName !== 'INPUT') {
    e.preventDefault();
    t.click();
  }
});
