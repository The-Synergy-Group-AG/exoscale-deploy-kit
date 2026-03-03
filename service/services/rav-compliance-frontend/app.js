// rav-compliance-frontend - Frontend Application
// Auto-generated from template

document.addEventListener('DOMContentLoaded', function() {
    const app = document.getElementById('app');
    const content = document.getElementById('content');

    // Initialize the application
    function initApp() {
        content.innerHTML = `
            <h2>Welcome to Rav-Compliance-Frontend</h2>
            <p>This is an auto-generated frontend service.</p>
            <p>Generated from template: ${template_data?.metadata?.name || 'unknown'}</p>
            <p>Timestamp: ${new Date().toISOString()}</p>
        `;

        console.log('rav-compliance-frontend frontend initialized');
    }

    // Start the application
    initApp();
});
