/**
 * Boot VK Mini App / community plugin shell.
 * Without VKWebAppInit the client often stays on a blank/loading screen.
 */
(function () {
  'use strict';

  function isVkShell() {
    try {
      var q = String(location.search || '');
      if (/(?:^\?|&)vk_app_id=/.test(q) || /(?:^\?|&)vk_platform=/.test(q)) return true;
      if (window.parent && window.parent !== window) {
        var ref = String(document.referrer || '');
        if (/vk\.(com|ru)|ok\.ru|mail\.ru/i.test(ref)) return true;
      }
    } catch (e) {}
    return false;
  }

  function markShell() {
    if (!isVkShell()) return false;
    try {
      document.documentElement.classList.add('vk-shell');
      if (document.body) document.body.classList.add('vk-shell');
    } catch (e) {}
    return true;
  }

  function invalidateMapSoon() {
    setTimeout(function () {
      try { window.dispatchEvent(new Event('resize')); } catch (e) {}
    }, 120);
    setTimeout(function () {
      try { window.dispatchEvent(new Event('resize')); } catch (e) {}
    }, 500);
  }

  function init() {
    markShell();
    var bridge = window.vkBridge || window.vkConnect;
    if (bridge && typeof bridge.send === 'function') {
      try { bridge.send('VKWebAppInit', {}); } catch (e) {}
      try {
        if (typeof bridge.subscribe === 'function') bridge.subscribe(function () {});
      } catch (e) {}
    }
    invalidateMapSoon();
    if (window.visualViewport) {
      window.visualViewport.addEventListener('resize', invalidateMapSoon);
      window.visualViewport.addEventListener('scroll', invalidateMapSoon);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
  // Class as early as possible for CSS.
  markShell();
})();
