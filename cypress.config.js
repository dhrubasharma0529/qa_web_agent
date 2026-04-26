const { defineConfig } = require("cypress");

module.exports = defineConfig({
  e2e: {
    // baseUrl is injected at runtime via --config baseUrl=<url> in run_cypress.
    // This fallback is only used when running Cypress manually outside the agent.
    baseUrl: "http://localhost:3000",

    // Where specs live
    specPattern: "cypress/e2e/**/*.cy.{js,jsx,ts,tsx}",
    supportFile: "cypress/support/e2e.js",

    // Viewport
    viewportWidth: 1280,
    viewportHeight: 720,

    // Timeouts
    defaultCommandTimeout: 10000,
    pageLoadTimeout: 30000,
    requestTimeout: 10000,

    // Video & screenshots
    video: false,
    screenshotOnRunFailure: true,
    screenshotsFolder: "cypress/screenshots",

    // Don't fail on uncaught exceptions from the app
    setupNodeEvents(on, config) {
      on("task", {
        log(message) {
          console.log(message);
          return null;
        },
      });
    },
  },
});
