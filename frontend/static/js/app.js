/**
 * PARK+ : Intelligent Parking & Vehicle Security Management System
 * Core Frontend Application Logic (Vanilla JavaScript + Chart.js)
 */

class ParkPlusApp {
  constructor() {
    this.currentPage = 'dashboard';
    this.refreshInterval = null;
    this.rfidCaptureRequestId = null;
    this.rfidCapturePollTimer = null;
    this.rfidCapturePolling = false;
    this.trafficChart = null;
    this.subsChart = null;
    this.peakHoursChart = null;
    this.cachedUsers = [];
    this.cachedPlans = [];
    this.pageGroups = {
      overview: [
        { id: 'dashboard', label: 'Dashboard' },
        { id: 'parking', label: 'Parking & Slots' }
      ],
      registry: [
        { id: 'customers', label: 'Customers' },
        { id: 'vehicles', label: 'Vehicles' },
        { id: 'rfid', label: 'RFID Cards' },
        { id: 'subscriptions', label: 'Subscriptions' }
      ],
      operations: [
        { id: 'security', label: 'Security' },
        { id: 'helpdesk', label: 'Helpdesk' },
        { id: 'devices', label: 'Devices' },
        { id: 'analytics', label: 'Analytics' },
        { id: 'settings', label: 'Settings' }
      ]
    };

    this.init();
  }

  async init() {
    this.setupNavigation();
    this.setupEventListeners();
    await this.checkAuth();
    this.navigateTo('dashboard');
    this.startAutoRefresh();
  }

  // ------------------------------------------------------------------------
  // Authentication & Session
  // ------------------------------------------------------------------------
  async checkAuth() {
    try {
      const res = await fetch('/api/auth/me');
      if (!res.ok) {
        window.location.href = '/login';
        return;
      }
      const data = await res.json();
      if (data.authenticated && data.admin) {
        const nameEl = document.getElementById('adminNameDisplay');
        const roleEl = document.getElementById('adminRoleDisplay');
        const avatarEl = document.getElementById('adminAvatar');
        if (nameEl) nameEl.textContent = data.admin.full_name;
        if (roleEl) roleEl.textContent = data.admin.role;
        if (avatarEl) avatarEl.textContent = data.admin.full_name.charAt(0).toUpperCase();
      }
    } catch (e) {
      window.location.href = '/login';
    }
  }

  async logout() {
    try {
      await fetch('/api/auth/logout', { method: 'POST' });
      window.location.href = '/login';
    } catch (e) {
      window.location.href = '/login';
    }
  }

  // ------------------------------------------------------------------------
  // Navigation
  // ------------------------------------------------------------------------
  setupNavigation() {
    document.querySelectorAll('.nav-group-item').forEach(item => {
      item.addEventListener('click', () => {
        const group = item.getAttribute('data-group');
        const firstPage = this.pageGroups[group]?.[0];
        if (firstPage) this.navigateTo(firstPage.id);
      });
    });

    const moduleTabs = document.getElementById('moduleTabs');
    if (moduleTabs) {
      moduleTabs.addEventListener('click', event => {
        const tab = event.target.closest('[data-page]');
        if (tab) this.navigateTo(tab.dataset.page);
      });
    }

    const mobileToggle = document.getElementById('mobileMenuToggle');
    const sidebar = document.getElementById('sidebar');
    if (mobileToggle && sidebar) {
      mobileToggle.addEventListener('click', () => {
        sidebar.classList.toggle('mobile-open');
      });
    }

    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
      logoutBtn.addEventListener('click', () => this.logout());
    }

    const refreshBtn = document.getElementById('refreshDataBtn');
    if (refreshBtn) {
      refreshBtn.addEventListener('click', () => this.refreshCurrentView());
    }

  }

  navigateTo(pageName) {
    this.currentPage = pageName;
    const group = this.getPageGroup(pageName);
    document.querySelectorAll('.nav-group-item').forEach(el => {
      el.classList.toggle('active', el.getAttribute('data-group') === group);
    });
    this.renderModuleTabs(group, pageName);

    document.querySelectorAll('.page-view').forEach(el => {
      el.style.display = 'none';
    });

    const targetView = document.getElementById(`view-${pageName}`);
    if (targetView) targetView.style.display = 'block';

    const titleEl = document.getElementById('pageTitle');
    const pageTitles = {
      dashboard: 'Dashboard Overview',
      parking: 'Parking & Slot Monitoring',
      customers: 'Customer Management',
      vehicles: 'Vehicle Registry',
      rfid: 'RFID Smart Card Management',
      subscriptions: 'Subscription Plans & Ledger',
      security: 'Security & Incident Management',
      helpdesk: 'Helpdesk & Support Tickets',
      devices: 'ESP32 & IoT Device Management',
      analytics: 'Analytics & Financial Reports',
      settings: 'System Configuration'
    };
    if (titleEl) titleEl.textContent = pageTitles[pageName] || 'Overview';

    // Close mobile drawer if open
    const sidebar = document.getElementById('sidebar');
    if (sidebar) sidebar.classList.remove('mobile-open');

    // Load view data
    this.refreshCurrentView();
  }

  getPageGroup(pageName) {
    return Object.entries(this.pageGroups).find(([, pages]) =>
      pages.some(page => page.id === pageName)
    )?.[0] || 'overview';
  }

  renderModuleTabs(group, activePage) {
    const container = document.getElementById('moduleTabs');
    if (!container) return;
    container.innerHTML = (this.pageGroups[group] || []).map(page => `
      <button type="button" class="module-tab ${page.id === activePage ? 'active' : ''}"
              data-page="${page.id}" aria-current="${page.id === activePage ? 'page' : 'false'}">
        ${page.label}
      </button>
    `).join('');
  }

  startAutoRefresh() {
    if (this.refreshInterval) clearInterval(this.refreshInterval);
    // Background polling every 4 seconds for live hardware telemetry
    this.refreshInterval = setInterval(() => {
      this.checkHeartbeat();
      if (this.currentPage === 'dashboard') {
        this.loadDashboard(true);
      } else if (this.currentPage === 'parking') {
        this.loadParkingSlots(true);
      }
    }, 4000);
  }

  refreshCurrentView() {
    this.checkHeartbeat();
    switch (this.currentPage) {
      case 'dashboard': this.loadDashboard(); break;
      case 'parking': this.loadParking(); break;
      case 'customers': this.loadCustomers(); break;
      case 'vehicles': this.loadVehicles(); break;
      case 'rfid': this.loadRfid(); break;
      case 'subscriptions': this.loadSubscriptions(); break;
      case 'security': this.loadSecurity(); break;
      case 'helpdesk': this.loadHelpdesk(); break;
      case 'devices': this.loadDevices(); break;
      case 'analytics': this.loadAnalytics(); break;
      case 'settings': this.loadSettings(); break;
    }
  }

  // ------------------------------------------------------------------------
  // IoT Device Heartbeat Monitor
  // ------------------------------------------------------------------------
  async checkHeartbeat() {
    try {
      const res = await fetch('/api/devices');
      if (!res.ok) return;
      const data = await res.json();
      if (data.devices && data.devices.length > 0) {
        const mainDevice = data.devices[0];
        const dot = document.getElementById('deviceStatusDot');
        const text = document.getElementById('deviceStatusText');
        if (dot && text) {
          if (mainDevice.is_online) {
            dot.className = 'status-dot online';
            text.textContent = `ESP32 Online (${mainDevice.device_code})`;
          } else {
            dot.className = 'status-dot offline';
            text.textContent = `ESP32 Offline`;
          }
        }
      }
    } catch (e) {
      // ignore
    }
  }

  // ------------------------------------------------------------------------
  // 1. DASHBOARD
  // ------------------------------------------------------------------------
  async loadDashboard(isSilent = false) {
    try {
      const [sumRes, chartRes, actRes] = await Promise.all([
        fetch('/api/dashboard/summary'),
        fetch('/api/dashboard/charts'),
        fetch('/api/dashboard/activity')
      ]);

      if (sumRes.ok) {
        const sumData = await sumRes.json();
        this.renderKpis(sumData.kpis);
        this.renderSlotsShowcase(sumData.slots, 'slotsShowcaseGrid');
      }

      if (actRes.ok) {
        const actData = await actRes.json();
        this.renderRecentScans(actData.scans);
      }

      if (!isSilent && chartRes.ok) {
        const chartData = await chartRes.json();
        this.renderDashboardCharts(chartData);
      }
    } catch (err) {
      if (!isSilent) this.showToast('Error refreshing dashboard data', 'error');
    }
  }

  renderKpis(kpis) {
    if (!kpis) return;
    const setTxt = (id, val) => {
      const el = document.getElementById(id);
      if (el) el.textContent = val !== undefined ? val : '--';
    };
    setTxt('kpiAvailableSlots', kpis.available_slots);
    setTxt('kpiVehiclesParked', kpis.vehicles_currently_parked);
    setTxt('kpiOccupiedSlots', kpis.occupied_slots);
    setTxt('kpiActiveSubs', kpis.active_subscriptions);
    setTxt('kpiTotalCustomers', kpis.total_customers);
    setTxt('kpiTodayEntries', kpis.today_entries);
    setTxt('kpiTodayExits', kpis.today_exits);
    setTxt('kpiActiveIncidents', kpis.active_security_incidents);
  }

  renderSlotsShowcase(slots, containerId) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (!slots || slots.length === 0) {
      container.innerHTML = '<div class="state-box">No parking slots configured.</div>';
      return;
    }

    container.innerHTML = slots.map(slot => {
      const isOccupied = !!slot.is_occupied;
      const statusClass = isOccupied ? 'occupied' : 'available';
      const statusText = isOccupied ? 'Occupied' : 'Available';
      const dist = slot.last_distance_cm !== null ? `${slot.last_distance_cm.toFixed(1)} cm` : 'No reading';
      const durationFmt = isOccupied && slot.duration_seconds ? this.formatSeconds(slot.duration_seconds) : '--';

      return `
        <div class="slot-card ${statusClass}">
          <div class="slot-banner">
            <div class="slot-id-badge">${slot.slot_code}</div>
            <div class="slot-state-badge ${statusClass}">${statusText}</div>
          </div>

          <div class="slot-details-list">
            <div class="slot-prop">
              <div class="slot-prop-label">Vehicle Plate</div>
              <div class="slot-prop-val">${slot.registration_number || 'None'}</div>
            </div>
            <div class="slot-prop">
              <div class="slot-prop-label">Customer</div>
              <div class="slot-prop-val">${slot.customer_name || 'N/A'}</div>
            </div>
            <div class="slot-prop">
              <div class="slot-prop-label">Sensor Distance</div>
              <div class="slot-prop-val">${dist}</div>
            </div>
            <div class="slot-prop">
              <div class="slot-prop-label">Park Duration</div>
              <div class="slot-prop-val">${durationFmt}</div>
            </div>
          </div>

          <div class="slot-sensor-bar">
            <span>IR Status: <strong>${(slot.last_sensor_status || 'healthy').toUpperCase()}</strong></span>
            <span>Session: <code>${slot.session_code || 'Idle'}</code></span>
          </div>
        </div>
      `;
    }).join('');
  }

  renderRecentScans(scans) {
    const tbody = document.getElementById('recentScansTableBody');
    if (!tbody) return;

    if (!scans || scans.length === 0) {
      tbody.innerHTML = '<tr><td colspan="7" class="text-center">No recent RFID scan logs.</td></tr>';
      return;
    }

    tbody.innerHTML = scans.map(s => {
      const timeFmt = new Date(s.scanned_at).toLocaleTimeString();
      const statusBadge = s.is_authorized 
        ? '<span class="badge badge-success">Authorized</span>' 
        : '<span class="badge badge-danger">Denied</span>';
      const typeBadge = s.scan_type === 'exit_gate'
        ? '<span class="badge badge-warning">Exit Gate</span>'
        : '<span class="badge badge-info">Entry Gate</span>';

      return `
        <tr>
          <td>${timeFmt}</td>
          <td><code>${s.card_uid}</code></td>
          <td>${s.customer_name || 'Unregistered'}</td>
          <td>${s.registration_number || 'N/A'}</td>
          <td>${typeBadge}</td>
          <td>${statusBadge}</td>
          <td>${s.is_authorized ? 'Barrier Opened' : `<small style="color:var(--color-danger);font-weight:700;">${s.denial_reason || 'Blocked'}</small>`}</td>
        </tr>
      `;
    }).join('');
  }

  renderDashboardCharts(chartData) {
    // 1. Daily Traffic Trend Chart
    const trafficCtx = document.getElementById('trafficTrendChart');
    if (trafficCtx && chartData.daily_trends) {
      if (this.trafficChart) this.trafficChart.destroy();
      this.trafficChart = new Chart(trafficCtx, {
        type: 'bar',
        data: {
          labels: chartData.daily_trends.labels,
          datasets: [
            {
              label: 'Entries',
              data: chartData.daily_trends.entries,
              backgroundColor: '#B8F35A',
              borderColor: '#171717',
              borderWidth: 2
            },
            {
              label: 'Exits',
              data: chartData.daily_trends.exits,
              backgroundColor: '#FF7A59',
              borderColor: '#171717',
              borderWidth: 2
            }
          ]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'top', labels: { font: { weight: 'bold' } } }
          },
          scales: {
            y: { beginAtZero: true, ticks: { stepSize: 1 } }
          }
        }
      });
    }

    // 2. Subscription Distribution Doughnut
    const subsCtx = document.getElementById('subscriptionDistChart');
    if (subsCtx && chartData.subscription_plans) {
      if (this.subsChart) this.subsChart.destroy();
      this.subsChart = new Chart(subsCtx, {
        type: 'doughnut',
        data: {
          labels: chartData.subscription_plans.labels,
          datasets: [{
            data: chartData.subscription_plans.counts,
            backgroundColor: ['#B8F35A', '#FF7A59', '#A9C7FF', '#FFD84D', '#70D6A3'],
            borderColor: '#171717',
            borderWidth: 2
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: {
            legend: { position: 'bottom', labels: { font: { weight: 'bold' } } }
          }
        }
      });
    }
  }

  // ------------------------------------------------------------------------
  // 2. PARKING & SESSIONS
  // ------------------------------------------------------------------------
  async loadParking() {
    this.loadParkingSlots();
    this.loadParkingSessions();
  }

  async loadParkingSlots(isSilent = false) {
    try {
      const res = await fetch('/api/parking/slots');
      if (res.ok) {
        const data = await res.json();
        this.renderSlotsShowcase(data.slots, 'parkingSlotsDetailedGrid');
      }
    } catch (e) {
      if (!isSilent) this.showToast('Error loading parking slots', 'error');
    }
  }

  async loadParkingSessions() {
    try {
      const status = document.getElementById('sessionStatusFilter')?.value || '';
      const url = status ? `/api/parking/sessions?status=${encodeURIComponent(status)}` : '/api/parking/sessions';
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('sessionsTableBody');
      if (!tbody) return;

      if (!data.sessions || data.sessions.length === 0) {
        tbody.innerHTML = '<tr><td colspan="9" class="text-center">No parking sessions found.</td></tr>';
        return;
      }

      tbody.innerHTML = data.sessions.map(s => {
        const statusBadge = s.status === 'active'
          ? '<span class="badge badge-warning">Active (Parked)</span>'
          : '<span class="badge badge-success">Completed</span>';
        const duration = this.formatSeconds(s.live_duration_seconds || s.duration_seconds);
        const billed = s.billed_amount_paise > 0 ? `₹${(s.billed_amount_paise / 100).toFixed(2)}` : 'Plan Quota';

        return `
          <tr>
            <td><code>${s.session_code}</code></td>
            <td><strong>${s.slot_code}</strong></td>
            <td>${s.registration_number}</td>
            <td>${s.customer_name}</td>
            <td>${new Date(s.entry_time).toLocaleString()}</td>
            <td>${s.exit_time ? new Date(s.exit_time).toLocaleString() : 'Parked'}</td>
            <td><strong>${duration}</strong></td>
            <td>${billed}</td>
            <td>${statusBadge}</td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      this.showToast('Error loading sessions', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 3. CUSTOMERS
  // ------------------------------------------------------------------------
  async loadCustomers() {
    try {
      const search = document.getElementById('customerSearchInput')?.value.trim() || '';
      const url = search ? `/api/users?search=${encodeURIComponent(search)}` : '/api/users';
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      this.cachedUsers = data.users || [];
      const tbody = document.getElementById('customersTableBody');
      if (!tbody) return;

      if (this.cachedUsers.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">No customers found.</td></tr>';
        return;
      }

      tbody.innerHTML = this.cachedUsers.map(u => {
        const statusClass = u.account_status === 'active' ? 'badge-success' : 'badge-danger';
        return `
          <tr>
            <td><code>${u.customer_code}</code></td>
            <td><strong>${u.full_name}</strong></td>
            <td>${u.email}</td>
            <td>${u.phone}</td>
            <td><span class="badge badge-neutral">${u.vehicle_count} Vehicles</span></td>
            <td><span class="badge badge-neutral">${u.card_count} Tags</span></td>
            <td><span class="badge ${statusClass}">${u.account_status}</span></td>
            <td>
              <button class="btn btn-sm btn-outline" onclick="app.editCustomer(${u.id})">Edit</button>
              <button class="btn btn-sm ${u.account_status === 'active' ? 'btn-danger' : 'btn-primary'}" 
                      onclick="app.toggleCustomerStatus(${u.id}, '${u.account_status}')">
                ${u.account_status === 'active' ? 'Deactivate' : 'Activate'}
              </button>
              <button class="btn btn-sm btn-danger" onclick="app.deleteCustomer(${u.id})">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      this.showToast('Error loading customers', 'error');
    }
  }

  openCustomerModal(user = null) {
    document.getElementById('custFormId').value = user ? user.id : '';
    document.getElementById('custFormName').value = user ? user.full_name : '';
    document.getElementById('custFormEmail').value = user ? user.email : '';
    document.getElementById('custFormPhone').value = user ? user.phone : '';
    document.getElementById('custFormAddress').value = user ? (user.address || '') : '';
    document.getElementById('custFormStatus').value = user ? user.account_status : 'active';
    document.getElementById('customerModalTitle').textContent = user ? 'Edit Customer' : 'Add Customer';
    this.openModal('customerModal');
  }

  editCustomer(userId) {
    const user = this.cachedUsers.find(u => u.id === userId);
    if (user) this.openCustomerModal(user);
  }

  async toggleCustomerStatus(userId, currentStatus) {
    const nextStatus = currentStatus === 'active' ? 'inactive' : 'active';
    try {
      const res = await fetch(`/api/users/${userId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: nextStatus })
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast(data.message, 'success');
        this.loadCustomers();
      } else {
        this.showToast(data.error || 'Failed to update status', 'error');
      }
    } catch (e) {
      this.showToast('Server communication error', 'error');
    }
  }

  async deleteCustomer(userId) {
    if (!confirm('Permanently delete this customer and linked history? This cannot be undone.')) return;
    try {
      const res = await fetch(`/api/users/${userId}`, {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ purge_history: true })
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast(data.message, 'success');
        this.loadCustomers();
      } else {
        this.showToast(data.error || 'Failed to delete customer', 'error');
      }
    } catch (e) {
      this.showToast('Error communicating with server', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 4. VEHICLES
  // ------------------------------------------------------------------------
  async loadVehicles() {
    try {
      const search = document.getElementById('vehicleSearchInput')?.value.trim() || '';
      const url = search ? `/api/vehicles?search=${encodeURIComponent(search)}` : '/api/vehicles';
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('vehiclesTableBody');
      if (!tbody) return;

      if (!data.vehicles || data.vehicles.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">No vehicles registered.</td></tr>';
        return;
      }

      tbody.innerHTML = data.vehicles.map(v => {
        return `
          <tr>
            <td><strong><code>${v.registration_number}</code></strong></td>
            <td>${v.customer_name}</td>
            <td><span class="badge badge-info">${v.vehicle_type.toUpperCase()}</span></td>
            <td>${v.model || 'N/A'}</td>
            <td>${v.color || 'N/A'}</td>
            <td>${v.linked_card_uid ? `<code>${v.linked_card_uid}</code>` : '<span style="color:#888;">None</span>'}</td>
            <td><span class="badge ${v.status === 'active' ? 'badge-success' : 'badge-danger'}">${v.status}</span></td>
            <td>
              <button class="btn btn-sm btn-danger" onclick="app.deleteVehicle(${v.id})">Delete</button>
            </td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      this.showToast('Error loading vehicles', 'error');
    }
  }

  async openVehicleModal() {
    await this.populateUserDropdown('vehFormUser');
    document.getElementById('vehFormId').value = '';
    document.getElementById('vehFormReg').value = '';
    document.getElementById('vehFormModel').value = '';
    document.getElementById('vehFormColor').value = '';
    this.openModal('vehicleModal');
  }

  async deleteVehicle(vehicleId) {
    if (!confirm('Are you sure you want to remove or deactivate this vehicle?')) return;
    try {
      const res = await fetch(`/api/vehicles/${vehicleId}`, { method: 'DELETE' });
      const data = await res.json();
      if (res.ok) {
        this.showToast(data.message, 'success');
        this.loadVehicles();
      } else {
        this.showToast(data.error || 'Failed to delete vehicle', 'error');
      }
    } catch (e) {
      this.showToast('Error communicating with server', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 5. RFID CARDS
  // ------------------------------------------------------------------------
  async loadRfid() {
    try {
      const [cardsRes, unregRes] = await Promise.all([
        fetch('/api/rfid/cards'),
        fetch('/api/rfid/unregistered')
      ]);

      if (cardsRes.ok) {
        const data = await cardsRes.json();
        const tbody = document.getElementById('rfidCardsTableBody');
        if (tbody) {
          if (!data.cards || data.cards.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" class="text-center">No RFID smart cards registered.</td></tr>';
          } else {
            tbody.innerHTML = data.cards.map(c => {
              const statusBadge = c.status === 'active' 
                ? '<span class="badge badge-success">Active</span>' 
                : (c.status === 'blocked' ? '<span class="badge badge-danger">Blocked</span>' : '<span class="badge badge-neutral">Inactive</span>');

              return `
                <tr>
                  <td><strong><code>${c.card_uid}</code></strong></td>
                  <td>${c.card_label || 'Smart Tag'}</td>
                  <td>${c.customer_name ? `${c.customer_name} (${c.customer_code})` : '<em style="color:#888;">Unassigned</em>'}</td>
                  <td>${c.registration_number || 'N/A'}</td>
                  <td>${statusBadge}</td>
                  <td>${c.last_used_at ? new Date(c.last_used_at).toLocaleString() : 'Never'}</td>
                  <td>
                    <button class="btn btn-sm ${c.status === 'active' ? 'btn-danger' : 'btn-primary'}" 
                            onclick="app.toggleCardStatus(${c.id}, '${c.status}')">
                      ${c.status === 'active' ? 'Block' : 'Activate'}
                    </button>
                  </td>
                </tr>
              `;
            }).join('');
          }
        }
      }

      if (unregRes.ok) {
        const unregData = await unregRes.json();
        const unregTbody = document.getElementById('unregisteredScansTableBody');
        if (unregTbody) {
          if (!unregData.unregistered_scans || unregData.unregistered_scans.length === 0) {
            unregTbody.innerHTML = '<tr><td colspan="6" class="text-center">No unauthorized RFID scans recorded.</td></tr>';
          } else {
            unregTbody.innerHTML = unregData.unregistered_scans.map(u => {
              return `
                <tr>
                  <td><strong><code>${u.card_uid}</code></strong></td>
                  <td>${u.device_code}</td>
                  <td><span style="color:var(--color-danger);font-weight:700;">${u.denial_reason}</span></td>
                  <td><span class="badge badge-warning">${u.attempt_count} Scans</span></td>
                  <td>${new Date(u.scanned_at).toLocaleTimeString()}</td>
                  <td>
                    <button class="btn btn-sm btn-primary" onclick="app.quickRegisterCard('${u.card_uid}')">Register Card</button>
                  </td>
                </tr>
              `;
            }).join('');
          }
        }
      }
    } catch (e) {
      this.showToast('Error loading RFID data', 'error');
    }
  }

  async openRfidModal() {
    await this.populateUserDropdown('rfidFormUser');
    await this.populateVehicleDropdown('rfidFormVehicle');
    document.getElementById('rfidFormUid').value = '';
    document.getElementById('rfidFormLabel').value = '';
    document.getElementById('rfidCaptureStatus').textContent =
      'Start a reader capture, then present the tag to the ESP32 reader.';
    this.openModal('rfidModal');
  }

  async requestRfidCapture() {
    if (this.rfidCaptureRequestId !== null) return;
    const button = document.getElementById('rfidCaptureBtn');
    const status = document.getElementById('rfidCaptureStatus');
    if (button) button.disabled = true;
    if (status) status.textContent = 'Requesting the ESP32 reader...';

    try {
      const res = await fetch('/api/rfid/capture/request', { method: 'POST' });
      const data = await res.json();
      if (res.status === 409 && Number.isInteger(data.request_id)) {
        this.rfidCaptureRequestId = data.request_id;
        if (status) status.textContent = 'An existing reader request was found. Resuming capture...';
      } else if (!res.ok) {
        throw new Error(data.error || 'Could not start RFID capture.');
      } else {
        if (!Number.isInteger(data.request_id)) {
          throw new Error('The server returned an invalid RFID capture request.');
        }
        this.rfidCaptureRequestId = data.request_id;
      }

      if (status && res.status !== 409) {
        status.textContent = 'Waiting for the ESP32 reader to acknowledge the request...';
      }
      this.showToast(
        res.status === 409 ? 'Resuming the pending RFID capture.' : 'RFID capture requested from the ESP32 reader.',
        'info'
      );
      this.rfidCapturePollTimer = setInterval(() => this.pollRfidCapture(), 1000);
      this.pollRfidCapture();
    } catch (error) {
      if (status) status.textContent = error.message;
      this.showToast(error.message, 'error');
    } finally {
      if (button) button.disabled = this.rfidCaptureRequestId !== null;
    }
  }

  async pollRfidCapture() {
    const requestId = this.rfidCaptureRequestId;
    if (requestId === null || this.rfidCapturePolling) return;

    this.rfidCapturePolling = true;
    try {
      const res = await fetch(`/api/rfid/capture/request/${requestId}`);
      const data = await res.json();
      if (requestId !== this.rfidCaptureRequestId) return;
      if (!res.ok) {
        if (res.status === 404) {
          document.getElementById('rfidCaptureStatus').textContent =
            'Reader request not found. Start a new capture.';
          this.finishRfidCapture();
          return;
        }
        throw new Error(data.error || 'Could not check reader status.');
      }

      if (data.status === 'captured') {
        document.getElementById('rfidFormUid').value = data.card_uid;
        document.getElementById('rfidCaptureStatus').textContent =
          `Tag ${data.card_uid} captured from the RC522 reader.`;
        this.finishRfidCapture();
        this.showToast(`RFID tag ${data.card_uid} captured.`, 'success');
      } else if (data.status === 'ready') {
        document.getElementById('rfidCaptureStatus').textContent =
          'Reader ready. Present the tag to the ESP32 RC522 reader now.';
      } else if (data.status !== 'pending') {
        document.getElementById('rfidCaptureStatus').textContent =
          data.status === 'expired' ? 'Reader request expired. Start a new capture.' : 'Reader request was cancelled.';
        this.finishRfidCapture();
      }
    } catch (error) {
      if (requestId === this.rfidCaptureRequestId) {
        document.getElementById('rfidCaptureStatus').textContent =
          `Reader status check failed; retrying. ${error.message}`;
      }
    } finally {
      this.rfidCapturePolling = false;
    }
  }

  finishRfidCapture() {
    if (this.rfidCapturePollTimer) clearInterval(this.rfidCapturePollTimer);
    this.rfidCapturePollTimer = null;
    this.rfidCaptureRequestId = null;
    const button = document.getElementById('rfidCaptureBtn');
    if (button) button.disabled = false;
  }

  async cancelRfidCapture() {
    const requestId = this.rfidCaptureRequestId;
    this.finishRfidCapture();
    if (requestId === null) return;
    try {
      await fetch(`/api/rfid/capture/request/${requestId}/cancel`, { method: 'POST' });
    } catch (error) {
      this.showToast('Could not cancel the RFID reader request.', 'error');
    }
  }

  quickRegisterCard(uid) {
    this.openRfidModal();
    document.getElementById('rfidFormUid').value = uid;
    document.getElementById('rfidFormLabel').value = `Scanned Tag ${uid}`;
  }

  async toggleCardStatus(cardId, currentStatus) {
    const next = currentStatus === 'active' ? 'blocked' : 'active';
    try {
      const res = await fetch(`/api/rfid/${cardId}/status`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: next })
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast(data.message, 'success');
        this.loadRfid();
      } else {
        this.showToast(data.error || 'Failed to update card status', 'error');
      }
    } catch (e) {
      this.showToast('Communication error', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 6. SUBSCRIPTIONS & LEDGER
  // ------------------------------------------------------------------------
  async loadSubscriptions() {
    try {
      const [plansRes, subsRes, txnsRes] = await Promise.all([
        fetch('/api/subscriptions/plans'),
        fetch('/api/subscriptions'),
        fetch('/api/subscriptions/transactions?limit=25')
      ]);

      if (plansRes.ok) {
        const pData = await plansRes.json();
        this.cachedPlans = pData.plans || [];
        const plansGrid = document.getElementById('subscriptionPlansGrid');
        if (plansGrid) {
          plansGrid.innerHTML = this.cachedPlans.map(p => {
            const hours = (p.allocated_seconds / 3600).toFixed(0);
            const inr = (p.price_paise / 100).toFixed(2);
            return `
              <div class="kpi-card ${p.plan_type === 'monthly' ? 'kpi-primary' : 'kpi-accent'}">
                <div class="kpi-label">${p.plan_type.toUpperCase()} PLAN</div>
                <div style="font-size: 20px; font-weight: 900; margin: 4px 0;">${p.name}</div>
                <div style="font-size: 28px; font-weight: 900;">₹${inr}</div>
                <div class="kpi-footer">Allocated: ${hours} Hours | Validity: ${p.duration_days} Days</div>
              </div>
            `;
          }).join('');
        }
      }

      if (subsRes.ok) {
        const sData = await subsRes.json();
        const tbody = document.getElementById('subscriptionsTableBody');
        if (tbody) {
          if (!sData.subscriptions || sData.subscriptions.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" class="text-center">No subscriptions found.</td></tr>';
          } else {
            tbody.innerHTML = sData.subscriptions.map(s => {
              const remFmt = this.formatSeconds(s.remaining_balance_seconds);
              const consFmt = this.formatSeconds(s.consumed_seconds);
              const statusClass = s.status === 'active' ? 'badge-success' : (s.status === 'expired' ? 'badge-danger' : 'badge-neutral');

              return `
                <tr>
                  <td><code>${s.subscription_code}</code></td>
                  <td><strong>${s.customer_name}</strong></td>
                  <td>${s.plan_name}</td>
                  <td><strong style="color:var(--color-border);font-size:15px;">${remFmt}</strong></td>
                  <td>${consFmt}</td>
                  <td>${new Date(s.expiry_date).toLocaleDateString()}</td>
                  <td><span class="badge ${statusClass}">${s.status}</span></td>
                  <td>
                    <button class="btn btn-sm btn-outline" onclick="app.viewTransactions(${s.id})">History</button>
                  </td>
                </tr>
              `;
            }).join('');
          }
        }
      }

      if (txnsRes.ok) {
        const tData = await txnsRes.json();
        const tbody = document.getElementById('transactionsTableBody');
        if (tbody) {
          tbody.innerHTML = tData.transactions.map(t => {
            const typeBadge = t.transaction_type === 'credit' 
              ? '<span class="badge badge-success">Credit</span>' 
              : (t.transaction_type === 'debit' ? '<span class="badge badge-info">Debit</span>' : '<span class="badge badge-danger">Overage</span>');
            const inr = t.amount_paise > 0 ? `₹${(t.amount_paise / 100).toFixed(2)}` : '₹0.00';

            return `
              <tr>
                <td><code>${t.transaction_code}</code></td>
                <td>${t.customer_name}</td>
                <td>${typeBadge}</td>
                <td><strong>${this.formatSeconds(t.seconds_amount)}</strong></td>
                <td>${this.formatSeconds(t.balance_after_seconds)}</td>
                <td>${inr}</td>
                <td>${new Date(t.created_at).toLocaleString()}</td>
                <td>${t.description}</td>
              </tr>
            `;
          }).join('');
        }
      }
    } catch (e) {
      this.showToast('Error loading subscription data', 'error');
    }
  }

  async openAssignSubModal() {
    await this.populateUserDropdown('assignSubUser');
    const planSelect = document.getElementById('assignSubPlan');
    if (planSelect) {
      planSelect.innerHTML = this.cachedPlans.map(p => {
        return `<option value="${p.id}">${p.name} - ₹${(p.price_paise/100).toFixed(2)} (${(p.allocated_seconds/3600)}h)</option>`;
      }).join('');
    }
    this.openModal('assignSubModal');
  }

  openPlanModal() {
    const form = document.getElementById('planForm');
    if (form) form.reset();
    this.openModal('planModal');
  }

  // ------------------------------------------------------------------------
  // 7. SECURITY INCIDENTS
  // ------------------------------------------------------------------------
  async loadSecurity() {
    await this.loadDepartureAlertThreshold();
    try {
      const severity = document.getElementById('incidentSeverityFilter')?.value || '';
      const status = document.getElementById('incidentStatusFilter')?.value || '';
      let url = '/api/security/events?';
      if (severity) url += `severity=${encodeURIComponent(severity)}&`;
      if (status) url += `status=${encodeURIComponent(status)}&`;

      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('incidentsTableBody');
      if (!tbody) return;

      if (!data.events || data.events.length === 0) {
        tbody.innerHTML = '<tr><td colspan="8" class="text-center">No security incidents logged.</td></tr>';
        return;
      }

      tbody.innerHTML = data.events.map(e => {
        const sevClass = e.severity === 'critical' ? 'badge-danger' : (e.severity === 'high' ? 'badge-warning' : 'badge-info');
        const statClass = e.status === 'open' ? 'badge-danger' : (e.status === 'investigating' ? 'badge-warning' : 'badge-success');

        return `
          <tr>
            <td><code>${e.event_code}</code></td>
            <td><strong>${e.event_type.replace('_', ' ').toUpperCase()}</strong></td>
            <td><span class="badge ${sevClass}">${e.severity}</span></td>
            <td>${e.description}</td>
            <td>${e.slot_code ? `Slot ${e.slot_code}` : (e.registration_number || 'Gate')}</td>
            <td><span class="badge ${statClass}">${e.status}</span></td>
            <td>${new Date(e.created_at).toLocaleString()}</td>
            <td>
              ${e.status !== 'resolved' ? `
                <button class="btn btn-sm btn-primary" onclick="app.updateIncidentStatus(${e.id}, 'resolved')">Resolve</button>
              ` : '<span style="color:#888;">Resolved</span>'}
            </td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      this.showToast('Error loading security incidents', 'error');
    }
  }

  async loadDepartureAlertThreshold() {
    const input = document.getElementById('departureAlertMinutes');
    if (!input) return;
    try {
      const res = await fetch('/api/settings');
      const data = await res.json();
      if (!res.ok) {
        this.showToast(data.error || 'Failed to load security threshold', 'error');
        return;
      }
      const setting = (data.settings || []).find(
        item => item.key === 'unscanned_departure_alert_minutes'
      );
      if (setting) input.value = setting.value;
    } catch (e) {
      this.showToast('Error loading security threshold', 'error');
    }
  }

  async saveDepartureAlertThreshold(e) {
    e.preventDefault();
    const minutes = Number(document.getElementById('departureAlertMinutes').value);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 1440) {
      this.showToast('Enter a whole number from 1 to 1440 minutes', 'error');
      return;
    }
    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ unscanned_departure_alert_minutes: minutes })
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast('Departure alert threshold saved', 'success');
      } else {
        this.showToast(data.error || 'Failed to save security threshold', 'error');
      }
    } catch (e) {
      this.showToast('Server communication error', 'error');
    }
  }

  async updateIncidentStatus(eventId, newStatus) {
    try {
      const res = await fetch(`/api/security/events/${eventId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: newStatus, investigation_notes: 'Resolved by Admin via Console.' })
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast(data.message, 'success');
        this.loadSecurity();
      } else {
        this.showToast(data.error || 'Failed to update incident', 'error');
      }
    } catch (e) {
      this.showToast('Communication error', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 8. HELPDESK
  // ------------------------------------------------------------------------
  async loadHelpdesk() {
    try {
      const res = await fetch('/api/helpdesk/tickets');
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('helpdeskTableBody');
      if (!tbody) return;

      if (!data.tickets || data.tickets.length === 0) {
        tbody.innerHTML = '<tr><td colspan="7" class="text-center">No support tickets found.</td></tr>';
        return;
      }

      tbody.innerHTML = data.tickets.map(t => {
        const priClass = t.priority === 'urgent' ? 'badge-danger' : (t.priority === 'high' ? 'badge-warning' : 'badge-neutral');
        const statClass = t.status === 'open' ? 'badge-danger' : (t.status === 'in_progress' ? 'badge-warning' : 'badge-success');

        return `
          <tr>
            <td><code>${t.ticket_code}</code></td>
            <td><strong>${t.subject}</strong><br><small style="color:var(--color-text-muted);">${t.description}</small></td>
            <td>${t.customer_name || 'Guest'}</td>
            <td><span class="badge ${priClass}">${t.priority}</span></td>
            <td><span class="badge ${statClass}">${t.status}</span></td>
            <td>${new Date(t.created_at).toLocaleDateString()}</td>
            <td>
              <button class="btn btn-sm btn-outline" onclick="app.closeTicket(${t.id})">Close Ticket</button>
            </td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      this.showToast('Error loading tickets', 'error');
    }
  }

  async closeTicket(id) {
    try {
      const res = await fetch(`/api/helpdesk/tickets/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status: 'closed', admin_response: 'Resolved and closed by admin.' })
      });
      if (res.ok) {
        this.showToast('Ticket closed', 'success');
        this.loadHelpdesk();
      }
    } catch (e) {
      this.showToast('Error updating ticket', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 9. IOT DEVICES
  // ------------------------------------------------------------------------
  async loadDevices() {
    try {
      const res = await fetch('/api/devices');
      if (!res.ok) return;
      const data = await res.json();
      const tbody = document.getElementById('devicesTableBody');
      if (!tbody) return;

      tbody.innerHTML = data.devices.map(d => {
        const isOnline = d.is_online;
        const statusBadge = isOnline 
          ? '<span class="badge badge-success">ONLINE</span>' 
          : '<span class="badge badge-danger">OFFLINE</span>';
        const lastSeen = d.last_seen_seconds_ago !== null ? `${d.last_seen_seconds_ago}s ago` : 'Never';

        return `
          <tr>
            <td><strong><code>${d.device_code}</code></strong></td>
            <td>${d.device_name}</td>
            <td>${d.device_type}</td>
            <td><code>${d.ip_address || 'N/A'}</code></td>
            <td>v${d.firmware_version}</td>
            <td>${statusBadge}</td>
            <td>${lastSeen}</td>
          </tr>
        `;
      }).join('');
    } catch (e) {
      this.showToast('Error loading device health', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // 10. ANALYTICS
  // ------------------------------------------------------------------------
  async loadAnalytics() {
    try {
      const res = await fetch('/api/analytics/overview');
      if (!res.ok) return;
      const data = await res.json();

      document.getElementById('analyticsAvgDuration').textContent = data.metrics.avg_duration_formatted || '--';
      document.getElementById('analyticsTotalRevenue').textContent = `₹${data.metrics.total_revenue_inr.toFixed(2)}`;
      document.getElementById('analyticsTotalSessions').textContent = data.metrics.total_sessions;

      // Peak Hours Chart
      const peakCtx = document.getElementById('peakHoursChart');
      if (peakCtx && data.peak_hours) {
        if (this.peakHoursChart) this.peakHoursChart.destroy();
        this.peakHoursChart = new Chart(peakCtx, {
          type: 'line',
          data: {
            labels: data.peak_hours.hours.map(h => `${h}:00`),
            datasets: [{
              label: 'Vehicle Influx Count',
              data: data.peak_hours.counts,
              borderColor: '#171717',
              backgroundColor: '#B8F35A',
              borderWidth: 3,
              fill: true,
              tension: 0.2
            }]
          },
          options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
              y: { beginAtZero: true, ticks: { stepSize: 1 } }
            }
          }
        });
      }
    } catch (e) {
      this.showToast('Error loading analytics', 'error');
    }
  }

  downloadReport(type) {
    window.open(`/api/analytics/export/csv?type=${encodeURIComponent(type)}`, '_blank');
  }

  // ------------------------------------------------------------------------
  // 11. SETTINGS
  // ------------------------------------------------------------------------
  async loadSettings() {
    try {
      const res = await fetch('/api/settings');
      if (!res.ok) return;
      const data = await res.json();
      const settingsMap = {};
      data.settings.forEach(s => { settingsMap[s.key] = s.value; });

      if (settingsMap['min_parking_allowance_seconds']) {
        document.getElementById('setting_min_allowance').value = settingsMap['min_parking_allowance_seconds'];
      }
      if (settingsMap['overage_rate_per_hour_paise']) {
        document.getElementById('setting_overage_rate').value = settingsMap['overage_rate_per_hour_paise'];
      }
      if (settingsMap['device_heartbeat_timeout_seconds']) {
        document.getElementById('setting_heartbeat_timeout').value = settingsMap['device_heartbeat_timeout_seconds'];
      }
      if (settingsMap['slot_distance_threshold_cm']) {
        document.getElementById('setting_slot_threshold').value = settingsMap['slot_distance_threshold_cm'];
      }
    } catch (e) {
      this.showToast('Error loading settings', 'error');
    }
  }

  async saveSettings(e) {
    e.preventDefault();
    const payload = {
      min_parking_allowance_seconds: document.getElementById('setting_min_allowance').value,
      overage_rate_per_hour_paise: document.getElementById('setting_overage_rate').value,
      device_heartbeat_timeout_seconds: document.getElementById('setting_heartbeat_timeout').value,
      slot_distance_threshold_cm: document.getElementById('setting_slot_threshold').value
    };

    try {
      const res = await fetch('/api/settings', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      const data = await res.json();
      if (res.ok) {
        this.showToast(data.message, 'success');
      } else {
        this.showToast(data.error || 'Failed to save settings', 'error');
      }
    } catch (e) {
      this.showToast('Server communication error', 'error');
    }
  }

  // ------------------------------------------------------------------------
  // Helpers & Event Listeners
  // ------------------------------------------------------------------------
  setupEventListeners() {
    // Customer Form Submit
    const custForm = document.getElementById('customerForm');
    if (custForm) {
      custForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const id = document.getElementById('custFormId').value;
        const payload = {
          full_name: document.getElementById('custFormName').value.trim(),
          email: document.getElementById('custFormEmail').value.trim(),
          phone: document.getElementById('custFormPhone').value.trim(),
          address: document.getElementById('custFormAddress').value.trim(),
          account_status: document.getElementById('custFormStatus').value
        };

        const method = id ? 'PUT' : 'POST';
        const url = id ? `/api/users/${id}` : '/api/users';

        try {
          const res = await fetch(url, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.ok) {
            this.showToast(data.message, 'success');
            this.closeModal('customerModal');
            this.loadCustomers();
          } else {
            this.showToast(data.error || 'Failed to save customer', 'error');
          }
        } catch (err) {
          this.showToast('Server error', 'error');
        }
      });
    }

    // Vehicle Form Submit
    const vehForm = document.getElementById('vehicleForm');
    if (vehForm) {
      vehForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
          user_id: document.getElementById('vehFormUser').value,
          registration_number: document.getElementById('vehFormReg').value.trim().toUpperCase(),
          vehicle_type: document.getElementById('vehFormType').value,
          model: document.getElementById('vehFormModel').value.trim(),
          color: document.getElementById('vehFormColor').value.trim()
        };

        try {
          const res = await fetch('/api/vehicles', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.ok) {
            this.showToast(data.message, 'success');
            this.closeModal('vehicleModal');
            this.loadVehicles();
          } else {
            this.showToast(data.error || 'Failed to register vehicle', 'error');
          }
        } catch (err) {
          this.showToast('Server error', 'error');
        }
      });
    }

    // RFID Form Submit
    const rfidForm = document.getElementById('rfidForm');
    if (rfidForm) {
      rfidForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
          card_uid: document.getElementById('rfidFormUid').value.trim().toUpperCase(),
          card_label: document.getElementById('rfidFormLabel').value.trim(),
          user_id: document.getElementById('rfidFormUser').value || null,
          vehicle_id: document.getElementById('rfidFormVehicle').value || null,
          status: 'active'
        };

        try {
          const res = await fetch('/api/rfid/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.ok) {
            this.showToast(data.message, 'success');
            this.closeModal('rfidModal');
            this.loadRfid();
          } else {
            this.showToast(data.error || 'Failed to register card', 'error');
          }
        } catch (err) {
          this.showToast('Server error', 'error');
        }
      });
    }

    // Assign Subscription Form Submit
    const assignSubForm = document.getElementById('assignSubForm');
    if (assignSubForm) {
      assignSubForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
          user_id: document.getElementById('assignSubUser').value,
          plan_id: document.getElementById('assignSubPlan').value
        };

        try {
          const res = await fetch('/api/subscriptions/assign', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.ok) {
            this.showToast(data.message, 'success');
            this.closeModal('assignSubModal');
            this.loadSubscriptions();
          } else {
            this.showToast(data.error || 'Failed to assign plan', 'error');
          }
        } catch (err) {
          this.showToast('Server error', 'error');
        }
      });
    }

    // Subscription Plan Form Submit
    const planForm = document.getElementById('planForm');
    if (planForm) {
      planForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const payload = {
          name: document.getElementById('planFormName').value.trim(),
          plan_type: document.getElementById('planFormType').value,
          duration_days: Number(document.getElementById('planFormDuration').value),
          allocated_hours: Number(document.getElementById('planFormHours').value),
          price_inr: Number(document.getElementById('planFormPrice').value),
          description: document.getElementById('planFormDescription').value.trim()
        };

        try {
          const res = await fetch('/api/subscriptions/plans', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
          });
          const data = await res.json();
          if (res.ok) {
            this.showToast(data.message, 'success');
            this.closeModal('planModal');
            this.loadSubscriptions();
          } else {
            this.showToast(data.error || 'Failed to create plan', 'error');
          }
        } catch (err) {
          this.showToast('Server error while creating plan', 'error');
        }
      });
    }

    // Settings Form Submit
    const settingsForm = document.getElementById('settingsForm');
    if (settingsForm) {
      settingsForm.addEventListener('submit', (e) => this.saveSettings(e));
    }

    const departureAlertSettingsForm = document.getElementById('departureAlertSettingsForm');
    if (departureAlertSettingsForm) {
      departureAlertSettingsForm.addEventListener(
        'submit',
        (e) => this.saveDepartureAlertThreshold(e)
      );
    }

    // Search and filter button triggers
    document.getElementById('customerSearchBtn')?.addEventListener('click', () => this.loadCustomers());
    document.getElementById('vehicleSearchBtn')?.addEventListener('click', () => this.loadVehicles());
    document.getElementById('filterSessionsBtn')?.addEventListener('click', () => this.loadParkingSessions());
    document.getElementById('filterIncidentsBtn')?.addEventListener('click', () => this.loadSecurity());
  }

  async populateUserDropdown(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    try {
      const res = await fetch('/api/users?status=active');
      const data = await res.json();
      sel.innerHTML = '<option value="">-- Select Customer --</option>' + 
        (data.users || []).map(u => `<option value="${u.id}">${u.full_name} (${u.customer_code})</option>`).join('');
    } catch (e) {}
  }

  async populateVehicleDropdown(selectId) {
    const sel = document.getElementById(selectId);
    if (!sel) return;
    try {
      const res = await fetch('/api/vehicles');
      const data = await res.json();
      sel.innerHTML = '<option value="">-- Select Vehicle (Optional) --</option>' + 
        (data.vehicles || []).map(v => `<option value="${v.id}">${v.registration_number} - ${v.customer_name}</option>`).join('');
    } catch (e) {}
  }

  formatSeconds(seconds) {
    if (!seconds || seconds <= 0) return '0s';
    const hrs = Math.floor(seconds / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    const secs = seconds % 60;
    if (hrs > 0) return `${hrs}h ${mins}m`;
    if (mins > 0) return `${mins}m ${secs}s`;
    return `${secs}s`;
  }

  openModal(modalId) {
    const m = document.getElementById(modalId);
    if (m) m.classList.add('active');
  }

  closeModal(modalId) {
    const m = document.getElementById(modalId);
    if (m) m.classList.remove('active');
    if (modalId === 'rfidModal') this.cancelRfidCapture();
  }

  showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
      <span>${message}</span>
      <button style="background:none;border:none;font-weight:900;cursor:pointer;">✕</button>
    `;

    toast.querySelector('button').addEventListener('click', () => toast.remove());
    container.appendChild(toast);

    setTimeout(() => {
      toast.remove();
    }, 4500);
  }
}

// Instantiate global app
window.app = new ParkPlusApp();

