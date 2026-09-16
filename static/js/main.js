document.addEventListener('DOMContentLoaded', () => {
    

    // Initialize Tooltips and Bootstrap components if any
    const tooltipTriggerList = [].slice.call(document.querySelectorAll('[data-bs-toggle="tooltip"]'));
    tooltipTriggerList.map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
});


