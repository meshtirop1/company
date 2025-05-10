document.addEventListener('DOMContentLoaded', function() {
    // Navbar toggle
    const navbarToggle = document.querySelector('.navbar-toggle');
    if (navbarToggle) {
        navbarToggle.addEventListener('click', function() {
            const navList = document.querySelector('.nav-list');
            const isExpanded = this.getAttribute('aria-expanded') === 'true';
            this.setAttribute('aria-expanded', !isExpanded);
            navList.classList.toggle('nav-list--open');
            this.querySelector('.navbar-toggle-icon').textContent = isExpanded ? '☰' : '✕';
            console.log('Navbar toggled, expanded:', !isExpanded);
        });
    }

    // Language switcher
    const languageForm = document.getElementById('language-form');
    const languageSelect = document.getElementById('language-select');
    if (languageForm && languageSelect) {
        languageSelect.addEventListener('change', function() {
            console.log('Language selected:', this.value);
            console.log('Form action:', languageForm.action);
            const formData = new FormData(languageForm);
            const formDataObj = Object.fromEntries(formData);
            console.log('Form data:', formDataObj);
            try {
                languageForm.submit();
                console.log('Language form submitted');
            } catch (error) {
                console.error('Error submitting language form:', error);
            }
        });

        languageForm.addEventListener('submit', function(event) {
            console.log('Language form submit event triggered');
        });
    } else {
        console.error('Language form or select not found');
    }
});