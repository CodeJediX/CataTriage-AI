function openCompetitionInvite() {
  const prefix = '#judge=';
  if (!window.location.hash.startsWith(prefix)) return;

  const code = window.location.hash.slice(prefix.length);
  // Fragments stay out of HTTP URLs. Clear the invite from the address bar before posting it.
  window.history.replaceState(null, '', '#competition-access');

  const panel = document.getElementById('competition-access');
  panel.open = true;
  panel.scrollIntoView({ block: 'nearest' });

  const form = document.getElementById('competition-invite');
  if (!form) return;

  const status = document.getElementById('competition-invite-status');
  if (!/^[a-f0-9]{24}$/.test(code)) {
    status.textContent = 'This invitation link is incomplete. Open the full link from the project team.';
    return;
  }

  status.textContent = 'Opening judge sign-ins…';
  form.elements.namedItem('access_code').value = code;
  form.requestSubmit();
}

openCompetitionInvite();
window.addEventListener('hashchange', openCompetitionInvite);
