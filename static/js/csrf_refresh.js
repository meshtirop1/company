// Keep every form's CSRF token in step with the csrftoken cookie.
//
// Django gives the browser a new CSRF token each time someone signs in. A page that was
// opened before that - brought back with the Back button, or a form tapped twice while the
// sign-in was finishing - still carries the old token, and Django refuses it with
// "CSRF verification failed". The cookie always holds the current token, and Django accepts
// it as the form value (the same way its docs describe for AJAX), so copy it into the forms
// whenever the page is shown and again just before any form is sent.
(function () {
    function currentToken() {
        var match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : null;
    }

    function refreshTokens() {
        var token = currentToken();
        if (!token) return;
        document.querySelectorAll('input[name="csrfmiddlewaretoken"]').forEach(function (input) {
            input.value = token;
        });
    }

    // pageshow also fires when Chrome restores a page from its back/forward cache.
    window.addEventListener('pageshow', refreshTokens);
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') refreshTokens();
    });
    // Capture phase, so the token is fresh before any other submit handler runs.
    document.addEventListener('submit', refreshTokens, true);
})();
