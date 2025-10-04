/**
 * Feature flags for the application
 * SERVER-SIDE ONLY - Do not import in client components
 * 
 * To enable/disable features, edit this file directly.
 * No rebuild required - just restart the dev server.
 */

export const features = {
  /**
   * Whether user registration is enabled
   * Set to true to allow new user sign-ups
   */
  registrationEnabled: false,
} as const

