from django.test import Client, TestCase
from django.urls import reverse

from .models import CustomUser


class StaleCsrfTokenTests(TestCase):
    """
    Forms sent from a page opened before the user signed in or out. Django gives the browser a
    new CSRF token at sign-in, so such a page's token no longer matches. static/js/csrf_refresh.js
    copies the csrftoken cookie into the forms; views.csrf_failure handles whatever still gets through.
    The normal test client skips CSRF checks, so these use one that enforces them.
    """

    password = 'not-a-real-pass-123'

    def setUp(self):
        CustomUser.objects.create_user(
            username='kim', email='kim@example.com', password=self.password, is_employee=True)
        self.client = Client(enforce_csrf_checks=True)

    def sign_in(self):
        """Sign in through the real form and return the token the sign-in page carried."""
        self.client.get(reverse('login'))
        token = self.client.cookies['csrftoken'].value
        response = self.client.post(reverse('login'), {
            'username': 'kim', 'password': self.password, 'csrfmiddlewaretoken': token})
        self.assertRedirects(response, reverse('calendar'), fetch_redirect_response=False)
        return token

    def test_signing_in_replaces_the_token(self):
        old = self.sign_in()
        self.assertNotEqual(self.client.cookies['csrftoken'].value, old)

    def test_the_cookie_value_is_accepted_as_the_form_token(self):
        # What csrf_refresh.js relies on: an old page's token is refused, the cookie's is accepted.
        old = self.sign_in()
        self.assertEqual(self.client.post(reverse('logout'), {'csrfmiddlewaretoken': old}).status_code, 403)
        response = self.client.post(
            reverse('logout'), {'csrfmiddlewaretoken': self.client.cookies['csrftoken'].value})
        self.assertRedirects(response, reverse('login'), fetch_redirect_response=False)

    def test_a_second_tap_on_sign_in_goes_to_the_calendar(self):
        old = self.sign_in()
        response = self.client.post(reverse('login'), {
            'username': 'kim', 'password': self.password, 'csrfmiddlewaretoken': old})
        self.assertRedirects(response, reverse('calendar'), fetch_redirect_response=False)

    def test_a_stale_form_gets_the_expired_page_with_a_reload_link(self):
        old = self.sign_in()
        response = self.client.post(reverse('logout'), {'csrfmiddlewaretoken': old},
                                    HTTP_REFERER='http://testserver/cutting/day/2026-10-02/?x=1')
        self.assertEqual(response.status_code, 403)
        self.assertTemplateUsed(response, 'csrf_failure_en.html')
        self.assertEqual(response.context['reload_url'], '/cutting/day/2026-10-02/?x=1')
        self.assertContains(response, 'href="/cutting/day/2026-10-02/?x=1"', status_code=403)
        # Nothing happened: still signed in.
        self.assertEqual(self.client.get(reverse('calendar')).status_code, 200)

    def test_the_reload_link_never_leaves_the_site(self):
        old = self.sign_in()
        response = self.client.post(reverse('logout'), {'csrfmiddlewaretoken': old},
                                    HTTP_REFERER='https://evil.example/cutting/')
        self.assertEqual(response.context['reload_url'], reverse('home'))

    def test_the_expired_page_follows_the_session_language(self):
        old = self.sign_in()
        session = self.client.session
        session['language'] = 'ko'
        session.save()
        response = self.client.post(reverse('logout'), {'csrfmiddlewaretoken': old})
        self.assertTemplateUsed(response, 'csrf_failure_ko.html')
        self.assertContains(response, '페이지가 만료되었습니다', status_code=403)
