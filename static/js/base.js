// PWA Install functionality variables
let deferredPrompt;
let installButton;

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

    // PWA Install functionality
    initializePWAInstall();
});

// PWA Install functionality
function initializePWAInstall() {
    // Create install button
    createInstallButton();
    
    // Check if app is already installed
    if (window.matchMedia('(display-mode: standalone)').matches) {
        console.log('🎉 App is already installed');
        hideInstallButton();
    }
}

// Listen for the beforeinstallprompt event
window.addEventListener('beforeinstallprompt', (e) => {
    console.log('🚀 beforeinstallprompt event fired');
    
    // Prevent the mini-infobar from appearing
    e.preventDefault();
    
    // Save the event so it can be triggered later
    deferredPrompt = e;
    
    // Show the install button
    showInstallButton();
});

// Create the install button
function createInstallButton() {
    // Check if button already exists
    if (document.getElementById('install-button')) return;
    
    installButton = document.createElement('button');
    installButton.id = 'install-button';
    installButton.innerHTML = '📱 Install App';
    installButton.style.cssText = `
        position: fixed;
        bottom: 20px;
        right: 20px;
        background: #007bff;
        color: white;
        border: none;
        padding: 12px 16px;
        border-radius: 8px;
        cursor: pointer;
        font-size: 14px;
        box-shadow: 0 4px 12px rgba(0,123,255,0.3);
        z-index: 1000;
        display: none;
        font-family: inherit;
        transition: all 0.3s ease;
        font-weight: 500;
    `;
    
    // Add hover effect
    installButton.addEventListener('mouseenter', () => {
        installButton.style.transform = 'translateY(-2px)';
        installButton.style.boxShadow = '0 6px 16px rgba(0,123,255,0.4)';
    });
    
    installButton.addEventListener('mouseleave', () => {
        installButton.style.transform = 'translateY(0)';
        installButton.style.boxShadow = '0 4px 12px rgba(0,123,255,0.3)';
    });
    
    installButton.addEventListener('click', installApp);
    document.body.appendChild(installButton);
    
    console.log('✅ Install button created');
}

// Show the install button
function showInstallButton() {
    if (installButton) {
        installButton.style.display = 'block';
        console.log('👀 Install button shown');
    }
}

// Hide the install button
function hideInstallButton() {
    if (installButton) {
        installButton.style.display = 'none';
        console.log('🙈 Install button hidden');
    }
}

// Handle the install button click
async function installApp() {
    console.log('🔥 Install button clicked');
    
    if (!deferredPrompt) {
        console.log('❌ No deferred prompt available');
        
        // Show helpful message
        showInstallMessage('Install prompt not available. Try visiting the site more or check if already installed.');
        return;
    }
    
    try {
        // Show the install prompt
        deferredPrompt.prompt();
        
        // Wait for the user to respond to the prompt
        const { outcome } = await deferredPrompt.userChoice;
        
        console.log(`✨ User response to the install prompt: ${outcome}`);
        
        if (outcome === 'accepted') {
            console.log('🎉 User accepted the install prompt');
            showInstallMessage('App is being installed...', 'success');
        } else {
            console.log('😔 User dismissed the install prompt');
        }
        
        // Clear the deferred prompt
        deferredPrompt = null;
        hideInstallButton();
        
    } catch (error) {
        console.error('❌ Error during installation:', error);
        showInstallMessage('Installation failed. Please try again.', 'error');
    }
}

// Show install message
function showInstallMessage(message, type = 'info') {
    const messageDiv = document.createElement('div');
    messageDiv.innerHTML = message;
    messageDiv.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        background: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : '#17a2b8'};
        color: white;
        padding: 12px 16px;
        border-radius: 8px;
        z-index: 1001;
        font-family: inherit;
        max-width: 300px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.2);
    `;
    document.body.appendChild(messageDiv);
    
    setTimeout(() => {
        if (document.body.contains(messageDiv)) {
            document.body.removeChild(messageDiv);
        }
    }, 4000);
}

// Listen for the app to be installed
window.addEventListener('appinstalled', (e) => {
    console.log('🎊 App was installed successfully');
    hideInstallButton();
    deferredPrompt = null;
    
    // Show success message
    showInstallMessage('✅ App installed successfully!', 'success');
});

// Debug function - you can call this in console
function checkPWAStatus() {
    console.log('=== 🔍 PWA Status Check ===');
    console.log('Service Worker supported:', 'serviceWorker' in navigator);
    
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.getRegistration().then(registration => {
            console.log('Service Worker registered:', !!registration);
            if (registration) {
                console.log('SW scope:', registration.scope);
                console.log('SW state:', registration.active ? registration.active.state : 'No active worker');
            }
        });
    }
    
    console.log('Deferred prompt available:', !!deferredPrompt);
    console.log('Display mode:', window.matchMedia('(display-mode: standalone)').matches ? 'standalone' : 'browser');
    console.log('Is installed:', window.matchMedia('(display-mode: standalone)').matches);
    
    // Check manifest
    const manifestLink = document.querySelector('link[rel="manifest"]');
    console.log('Manifest link found:', !!manifestLink);
    if (manifestLink) {
        console.log('Manifest URL:', manifestLink.href);
        
        // Try to fetch manifest
        fetch(manifestLink.href)
            .then(response => {
                console.log('Manifest fetch status:', response.status);
                return response.json();
            })
            .then(manifest => {
                console.log('Manifest loaded successfully:', manifest.name);
            })
            .catch(error => {
                console.error('Manifest fetch error:', error);
            });
    }
    
    // Check icons
    const icons = document.querySelectorAll('link[rel*="icon"]');
    console.log('Icons found:', icons.length);
    
    // Check HTTPS
    console.log('HTTPS:', location.protocol === 'https:');
    
    console.log('=== End PWA Status ===');
}

// Make checkPWAStatus available globally for debugging
window.checkPWAStatus = checkPWAStatus;

// Auto-run PWA status check in development
if (location.hostname === 'localhost' || location.hostname === '127.0.0.1') {
    setTimeout(checkPWAStatus, 2000);
}