/**
 * Second-line access guard inside VK Mini App WebView.
 * Does not replace VK "Состояние = Выключено"; hardens against casual link sharing.
 */
(function () {
  'use strict';

  function parseLaunchParams() {
    var out = {};
    var q = String(location.search || '').replace(/^\?/, '');
    if (!q) return out;
    q.split('&').forEach(function (pair) {
      var i = pair.indexOf('=');
      if (i < 0) return;
      var k = decodeURIComponent(pair.slice(0, i).replace(/\+/g, ' '));
      var v = decodeURIComponent(pair.slice(i + 1).replace(/\+/g, ' '));
      out[k] = v;
    });
    return out;
  }

  function isVkLaunch(params) {
    return !!(params.vk_app_id || params.vk_platform || params.vk_user_id);
  }

  function toInt(v) {
    var n = parseInt(String(v || ''), 10);
    return isFinite(n) ? n : 0;
  }

  function roleOk(role) {
    return role === 'member' || role === 'moder' || role === 'editor' || role === 'admin';
  }

  function showBlocked(reason) {
    try {
      document.documentElement.style.overflow = 'hidden';
    } catch (e) {}
    var overlay = document.createElement('div');
    overlay.id = 'tz-vk-access-block';
    overlay.setAttribute('role', 'alert');
    overlay.style.cssText = [
      'position:fixed',
      'inset:0',
      'z-index:2147483646',
      'display:flex',
      'align-items:center',
      'justify-content:center',
      'padding:24px',
      'background:#0f172a',
      'color:#e2e8f0',
      'font:16px/1.45 system-ui,sans-serif',
      'text-align:center'
    ].join(';');
    overlay.innerHTML =
      '<div style="max-width:420px">' +
      '<div style="font-size:20px;font-weight:700;margin-bottom:10px">Доступ закрыт</div>' +
      '<div style="opacity:.9;margin-bottom:14px">' +
      (reason || 'Карта доступна только участникам закрытого сообщества и администраторам приложения.') +
      '</div>' +
      '<div style="opacity:.65;font-size:13px">Откройте приложение из меню группы или попросите админа добавить вас.</div>' +
      '</div>';
    function mount() {
      if (!document.body) return false;
      if (!document.getElementById('tz-vk-access-block')) document.body.appendChild(overlay);
      try {
        document.body.style.visibility = 'hidden';
        overlay.style.visibility = 'visible';
        document.body.style.visibility = 'visible';
        Array.prototype.forEach.call(document.body.children, function (el) {
          if (el !== overlay) el.style.display = 'none';
        });
      } catch (e) {}
      return true;
    }
    if (!mount()) {
      document.addEventListener('DOMContentLoaded', mount);
    }
  }

  function decide() {
    var cfg = window.TZ_VK_ACCESS || {};
    var params = parseLaunchParams();
    if (!isVkLaunch(params)) {
      // Outside VK (GitHub Pages / bothost) — do not lock the public map page here.
      return { ok: true };
    }

    var appId = toInt(params.vk_app_id);
    var expectApp = toInt(cfg.APP_ID) || 54706281;
    if (appId && appId !== expectApp) {
      return { ok: false, reason: 'Это другая копия приложения.' };
    }

    var userId = toInt(params.vk_user_id);
    var allowed = Array.isArray(cfg.ALLOWED_USER_IDS) ? cfg.ALLOWED_USER_IDS : [];
    for (var i = 0; i < allowed.length; i++) {
      if (toInt(allowed[i]) === userId) return { ok: true };
    }

    var groupId = toInt(params.vk_group_id);
    var expectGroup = toInt(cfg.GROUP_ID);
    var role = String(params.vk_viewer_group_role || '').toLowerCase();

    if (expectGroup > 0) {
      if (groupId === expectGroup && roleOk(role)) return { ok: true };
      if (groupId && groupId !== expectGroup) {
        return { ok: false, reason: 'Приложение привязано к другому сообществу.' };
      }
      if (groupId === expectGroup && !roleOk(role)) {
        return { ok: false, reason: 'Нужно быть участником закрытого сообщества.' };
      }
      // Opened without group context: only if direct launch allowed (app admins via VK panel).
      if (!groupId && cfg.ALLOW_DIRECT_VK_LAUNCH !== false) return { ok: true };
      return { ok: false, reason: 'Откройте карту из меню закрытого сообщества.' };
    }

    // GROUP_ID not configured yet: rely on VK panel disable + optional role if present.
    if (groupId && role && !roleOk(role)) {
      return { ok: false, reason: 'Нужно быть участником сообщества.' };
    }
    return { ok: true };
  }

  var result = decide();
  if (!result.ok) {
    showBlocked(result.reason);
    try {
      window.__TZ_VK_ACCESS_DENIED__ = true;
    } catch (e) {}
  }
})();
