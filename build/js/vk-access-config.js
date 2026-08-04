/**
 * Access policy for the VK Mini App shell.
 * Edit GROUP_ID / ALLOWED_USER_IDS after you know numeric IDs.
 *
 * Primary lock is still VK panel: Размещение → Состояние = Выключено
 * (only app admins + testers can open). This file is a second line of defense.
 */
window.TZ_VK_ACCESS = {
  /** Must match the Mini App id */
  APP_ID: 54706281,

  /**
   * Closed community id WITHOUT minus sign (e.g. 123456789).
   * Leave 0 until filled — then only group members/staff pass when opened from the group.
   */
  GROUP_ID: 0,

  /**
   * Extra VK user ids allowed even without group role (optional).
   * Example: [100, 200]
   */
  ALLOWED_USER_IDS: [],

  /**
   * When true, opening vk.com/app… without group context is allowed
   * (needed for app admins while Состояние = Выключено).
   */
  ALLOW_DIRECT_VK_LAUNCH: true
};
