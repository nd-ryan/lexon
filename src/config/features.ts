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
  registrationEnabled: true,

  /**
   * Access code required for registration (optional extra security)
   * When set to a non-empty string, users must enter this code to register.
   * Set to null or '' to disable access code requirement.
   * 
   * Example: 'client-team-2026'
   */
  registrationAccessCode: 'advocacy-team-2026' as string | null,
  
} as const

