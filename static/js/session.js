/**
 * Client-side session inactivity guard.
 * Mirrors the server-side SESSION_TIMEOUT_MINUTES (30 min).
 * After 25 min of inactivity a warning banner is shown.
 * After 30 min the page is redirected to /login?expired=1.
 *
 * Include this script in every authenticated page (NOT the login page).
 */
(function () {
  var TIMEOUT_MS = 30 * 60 * 1000;   // 30 minutes — must match server value
  var WARN_MS    = 25 * 60 * 1000;   // show warning 5 minutes before timeout
  var lastActivity = Date.now();
  var warnTimer, logoutTimer;

  function resetTimers() {
    lastActivity = Date.now();
    clearTimeout(warnTimer);
    clearTimeout(logoutTimer);
    var banner = document.getElementById('session-expiry-warning');
    if (banner) banner.style.display = 'none';

    warnTimer = setTimeout(function () {
      var b = document.getElementById('session-expiry-warning');
      if (b) b.style.display = 'block';
    }, WARN_MS);

    logoutTimer = setTimeout(function () {
      window.location.href = '/login?expired=1';
    }, TIMEOUT_MS);
  }

  // Reset on any user interaction
  ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll', 'click'].forEach(function (evt) {
    document.addEventListener(evt, resetTimers, { passive: true });
  });

  // Redirect if coming back via history after a long absence
  window.addEventListener('pageshow', function (e) {
    if (e.persisted && Date.now() - lastActivity >= TIMEOUT_MS) {
      window.location.href = '/login?expired=1';
    }
  });

  // Start counting
  resetTimers();
})();
