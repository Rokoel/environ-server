/**
 * Environ Server - Main JavaScript
 * Material You styling and functionality
 */

(function() {
    'use strict';

    // ==========================================================================
    // Theme Management
    // ==========================================================================
    const ThemeManager = {
        THEME_KEY: 'environ-server-theme',

        init() {
            const savedTheme = localStorage.getItem(this.THEME_KEY);
            const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;

            if (savedTheme) {
                this.setTheme(savedTheme);
            } else if (prefersDark) {
                this.setTheme('dark');
            }

            this.bindEvents();
        },

        setTheme(theme) {
            document.documentElement.setAttribute('data-theme', theme);
            localStorage.setItem(this.THEME_KEY, theme);
        },

        toggle() {
            const currentTheme = document.documentElement.getAttribute('data-theme');
            const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
            this.setTheme(newTheme);
        },

        bindEvents() {
            const themeToggle = document.getElementById('themeToggle');
            if (themeToggle) {
                themeToggle.addEventListener('click', () => this.toggle());
            }

            // Listen for system theme changes
            window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
                if (!localStorage.getItem(this.THEME_KEY)) {
                    this.setTheme(e.matches ? 'dark' : 'light');
                }
            });
        }
    };

    // ==========================================================================
    // Video Background Management
    // ==========================================================================
    const VideoManager = {
        init() {
            const video = document.getElementById('bgVideo');
            if (!video) return;

            // Handle video errors
            video.addEventListener('error', () => {
                console.log('Video failed to load, using fallback');
                video.style.display = 'none';
                const container = document.querySelector('.video-container');
                if (container) {
                    container.classList.add('video-fallback');
                }
            });

            // Check if video can play
            video.addEventListener('canplay', () => {
                video.style.display = 'block';
            });

            // Handle visibility change to save resources
            document.addEventListener('visibilitychange', () => {
                if (document.hidden) {
                    video.pause();
                } else {
                    video.play().catch(() => {});
                }
            });

            // Fallback timeout - if video doesn't load in 5 seconds, show fallback
            setTimeout(() => {
                if (video.readyState < 2) {
                    video.style.display = 'none';
                    const container = document.querySelector('.video-container');
                    if (container) {
                        container.classList.add('video-fallback');
                    }
                }
            }, 5000);
        }
    };

    // ==========================================================================
    // Scroll Animations
    // ==========================================================================
    const ScrollAnimation = {
        init() {
            const observerOptions = {
                threshold: 0.2,
                rootMargin: '0px 0px -50px 0px'
            };

            const observer = new IntersectionObserver((entries) => {
                entries.forEach(entry => {
                    if (entry.isIntersecting) {
                        entry.target.classList.add('visible');
                    }
                });
            }, observerOptions);

            // Observe info blocks
            document.querySelectorAll('.info-block').forEach(block => {
                observer.observe(block);
            });

            // Observe application cards
            document.querySelectorAll('.application-card').forEach(card => {
                observer.observe(card);
            });
        }
    };

    // ==========================================================================
    // File Upload Handler
    // ==========================================================================
    const FileUploadHandler = {
        init() {
            const fileInputs = document.querySelectorAll('.file-input');

            fileInputs.forEach(input => {
                const wrapper = input.closest('.file-upload-area');
                if (!wrapper) return;

                const placeholder = wrapper.querySelector('.file-upload-placeholder');

                // Handle file selection
                input.addEventListener('change', () => {
                    if (input.files && input.files[0]) {
                        const fileName = input.files[0].name;
                        const fileSize = input.files[0].size;
                        const maxSize = 30 * 1024 * 1024; // 30MB

                        // Check file size
                        if (fileSize > maxSize) {
                            alert('Файл слишком большой. Максимальный размер: 30MB');
                            input.value = '';
                            return;
                        }

                        // Update placeholder
                        if (placeholder) {
                            placeholder.innerHTML = `
                                <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                                    <polyline points="14 2 14 8 20 8"></polyline>
                                </svg>
                                <span>${fileName}</span>
                                <small>${this.formatFileSize(fileSize)}</small>
                            `;
                            placeholder.classList.add('file-selected');
                        }
                    }
                });

                // Drag and drop
                wrapper.addEventListener('dragover', (e) => {
                    e.preventDefault();
                    wrapper.classList.add('drag-over');
                });

                wrapper.addEventListener('dragleave', () => {
                    wrapper.classList.remove('drag-over');
                });

                wrapper.addEventListener('drop', (e) => {
                    e.preventDefault();
                    wrapper.classList.remove('drag-over');

                    if (e.dataTransfer.files && e.dataTransfer.files[0]) {
                        input.files = e.dataTransfer.files;
                        input.dispatchEvent(new Event('change'));
                    }
                });
            });
        },

        formatFileSize(bytes) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const sizes = ['Bytes', 'KB', 'MB', 'GB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
        }
    };

    // ==========================================================================
    // Form Validation
    // ==========================================================================
    const FormValidator = {
        init() {
            const forms = document.querySelectorAll('form[data-validate]');

            forms.forEach(form => {
                form.addEventListener('submit', (e) => {
                    if (!this.validate(form)) {
                        e.preventDefault();
                    }
                });
            });
        },

        validate(form) {
            let isValid = true;
            const requiredFields = form.querySelectorAll('[required]');

            requiredFields.forEach(field => {
                if (!field.value.trim()) {
                    isValid = false;
                    field.classList.add('error');
                } else {
                    field.classList.remove('error');
                }
            });

            if (!isValid) {
                this.showError('Пожалуйста, заполните все обязательные поля');
            }

            return isValid;
        },

        showError(message) {
            // Create flash message
            const flashContainer = document.querySelector('.flash-messages') || this.createFlashContainer();

            const flash = document.createElement('div');
            flash.className = 'flash-message flash-error';
            flash.innerHTML = `
                <span>${message}</span>
                <button class="flash-close" onclick="this.parentElement.remove()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            `;

            flashContainer.appendChild(flash);

            // Auto-remove after 5 seconds
            setTimeout(() => {
                flash.remove();
            }, 5000);
        },

        createFlashContainer() {
            const container = document.createElement('div');
            container.className = 'flash-messages';
            document.body.appendChild(container);
            return container;
        }
    };

    // ==========================================================================
    // Admin Filter/Sort
    // ==========================================================================
    const AdminManager = {
        init() {
            this.bindFilterEvents();
            this.bindModalEvents();
        },

        applyFilter() {
            const status = document.getElementById('statusFilter')?.value || 'all';
            const sort = document.getElementById('sortBy')?.value || 'created_at';
            const order = document.querySelector('.sort-order svg')?.style.transform === 'rotate(180deg)' ? 'desc' : 'asc';

            const url = new URL(window.location.href);
            url.searchParams.set('status', status);
            url.searchParams.set('sort', sort);
            url.searchParams.set('order', order);

            window.location.href = url.toString();
        },

        toggleSortOrder() {
            const button = document.querySelector('.sort-order svg');
            if (button) {
                const currentTransform = button.style.transform;
                if (currentTransform === 'rotate(180deg)') {
                    button.style.transform = 'rotate(0deg)';
                } else {
                    button.style.transform = 'rotate(180deg)';
                }
            }
        },

        showRejectModal(userId, currentStatus) {
            const modal = document.getElementById('rejectModal');
            const form = document.getElementById('rejectForm');

            if (modal && form) {
                form.action = `/admin/user/${userId}/status`;
                modal.classList.add('show');
            }
        },

        closeRejectModal() {
            const modal = document.getElementById('rejectModal');
            if (modal) {
                modal.classList.remove('show');
            }
        },

        bindFilterEvents() {
            const statusFilter = document.getElementById('statusFilter');
            const sortBy = document.getElementById('sortBy');
            const sortOrder = document.querySelector('.sort-order');

            if (statusFilter) {
                statusFilter.addEventListener('change', () => this.applyFilter());
            }

            if (sortBy) {
                sortBy.addEventListener('change', () => this.applyFilter());
            }

            if (sortOrder) {
                sortOrder.addEventListener('click', () => {
                    this.toggleSortOrder();
                    this.applyFilter();
                });
            }
        },

        bindModalEvents() {
            const modal = document.getElementById('rejectModal');

            if (modal) {
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) {
                        this.closeRejectModal();
                    }
                });

                // Close on escape
                document.addEventListener('keydown', (e) => {
                    if (e.key === 'Escape' && modal.classList.contains('show')) {
                        this.closeRejectModal();
                    }
                });
            }
        }
    };

    // ==========================================================================
    // Utility Functions
    // ==========================================================================
    const Utilities = {
        // Copy text to clipboard
        copyToClipboard(text) {
            if (navigator.clipboard) {
                navigator.clipboard.writeText(text).then(() => {
                    this.showNotification('Скопировано в буфер обмена!', 'success');
                }).catch(() => {
                    this.showNotification('Не удалось скопировать', 'error');
                });
            } else {
                // Fallback for older browsers
                const textarea = document.createElement('textarea');
                textarea.value = text;
                textarea.style.position = 'fixed';
                textarea.style.opacity = '0';
                document.body.appendChild(textarea);
                textarea.select();
                try {
                    document.execCommand('copy');
                    this.showNotification('Скопировано в буфер обмена!', 'success');
                } catch (err) {
                    this.showNotification('Не удалось скопировать', 'error');
                }
                document.body.removeChild(textarea);
            }
        },

        // Show notification
        showNotification(message, type = 'info') {
            const flashContainer = document.querySelector('.flash-messages') || this.createFlashContainer();

            const flash = document.createElement('div');
            flash.className = `flash-message flash-${type}`;
            flash.innerHTML = `
                <span>${message}</span>
                <button class="flash-close" onclick="this.parentElement.remove()">
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <line x1="18" y1="6" x2="6" y2="18"></line>
                        <line x1="6" y1="6" x2="18" y2="18"></line>
                    </svg>
                </button>
            `;

            flashContainer.appendChild(flash);

            setTimeout(() => {
                flash.remove();
            }, 3000);
        },

        createFlashContainer() {
            const container = document.createElement('div');
            container.className = 'flash-messages';
            document.body.appendChild(container);
            return container;
        },

        // Debounce function
        debounce(func, wait) {
            let timeout;
            return function executedFunction(...args) {
                const later = () => {
                    clearTimeout(timeout);
                    func(...args);
                };
                clearTimeout(timeout);
                timeout = setTimeout(later, wait);
            };
        },

        // Smooth scroll to element
        smoothScrollTo(elementId) {
            const element = document.getElementById(elementId);
            if (element) {
                element.scrollIntoView({ behavior: 'smooth' });
            }
        }
    };

    // ==========================================================================
    // Download Button Handler
    // ==========================================================================
    const DownloadManager = {
        init() {
            const downloadButtons = document.querySelectorAll('.download-button');

            downloadButtons.forEach(button => {
		    button.addEventListener('click', (e) => {

			const filename = button.getAttribute('data-filename');
			const telegramId = button.getAttribute('data-user-id') || '';

			if (telegramId) {
			    e.preventDefault();
			    window.location.href = `/uploads/${telegramId}/${filename}`;
			}
		    });
		});
        }
    };
    
    // ==========================================================================
    // Player Count Manager (Header)
    // ==========================================================================
    const PlayerCountManager = {
        updateInterval: 30000, // 30 seconds
        intervalId: null,

        init() {
            // Only run on pages with header player count
            const headerPlayerEl = document.getElementById('headerPlayerNumber');
            if (!headerPlayerEl) return;
            
            const headerPlayerCount = document.getElementById('headerPlayerCount');
            headerPlayerCount.addEventListener('click', (e) => {
            	window.location.href = "/map";
            });

            this.update();
            this.intervalId = setInterval(() => this.update(), this.updateInterval);
        },

        update() {
            fetch('/api/server-status')
                .then(response => response.json())
                .then(data => {
                    const headerPlayerEl = document.getElementById('headerPlayerNumber');
                    const headerCard = document.getElementById('headerPlayerCount');

                    if (headerPlayerEl) {
                        headerPlayerEl.textContent = data.online ? data.players_online : '0';
                    }

                    if (headerCard) {
                        headerCard.classList.toggle('online', data.online);
                    }
                })
                .catch(error => {
                    console.log('Failed to fetch server status:', error);
                    const headerPlayerEl = document.getElementById('headerPlayerNumber');
                    if (headerPlayerEl) {
                        headerPlayerEl.textContent = '0';
                    }
                });
        }
    };

    // ==========================================================================
    // Initialize Everything
    // ==========================================================================
    document.addEventListener('DOMContentLoaded', function() {
        // Initialize all managers
        ThemeManager.init();
        VideoManager.init();
        ScrollAnimation.init();
        FileUploadHandler.init();
        FormValidator.init();
        AdminManager.init();
        DownloadManager.init();
        PlayerCountManager.init();

        // Make utilities globally accessible
        window.EnvironServer = {
            copyToClipboard: Utilities.copyToClipboard.bind(Utilities),
            showNotification: Utilities.showNotification.bind(Utilities),
            smoothScrollTo: Utilities.smoothScrollTo.bind(Utilities),
            applyFilter: AdminManager.applyFilter.bind(AdminManager),
            toggleSortOrder: AdminManager.toggleSortOrder.bind(AdminManager),
            showRejectModal: AdminManager.showRejectModal.bind(AdminManager),
            closeRejectModal: AdminManager.closeRejectModal.bind(AdminManager)
        };

        console.log('Environ Server initialized');
    });

    // ==========================================================================
    // Global Functions (for inline event handlers)
    // ==========================================================================
    window.copyToClipboard = function(text) {
        Utilities.copyToClipboard(text);
    };

    window.scrollToContent = function() {
        const infoSection = document.getElementById('infoSection');
        if (infoSection) {
            infoSection.scrollIntoView({ behavior: 'smooth' });
        }
    };

    window.applyFilter = function() {
        AdminManager.applyFilter();
    };

    window.toggleSortOrder = function() {
        AdminManager.toggleSortOrder();
    };

    window.showRejectModal = function(userId, currentStatus) {
        AdminManager.showRejectModal(userId, currentStatus);
    };

    window.closeRejectModal = function() {
        AdminManager.closeRejectModal();
    };

})();
