// ***********************************************************
// This file is processed and loaded automatically before
// your test files.
//
// You can read more here:
// https://on.cypress.io/configuration
// ***********************************************************

// Import commands.js
import "./commands";

// Prevent Cypress from failing tests due to uncaught exceptions
// from the application under test
Cypress.on("uncaught:exception", (err, runnable) => {
  // Returning false here prevents Cypress from failing the test
  return false;
});

// Apply step delay after each test when CYPRESS_STEP_DELAY_MS > 0
// Set via --env stepDelay=500 in the cypress run command (configured in src/config.py)
afterEach(() => {
  const delay = Cypress.env("stepDelay");
  if (delay && delay > 0) {
    cy.wait(delay);
  }
});
