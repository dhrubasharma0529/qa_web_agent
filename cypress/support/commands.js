// ***********************************************
// Custom commands for QA-Web-Agent
// https://on.cypress.io/custom-commands
// ***********************************************

// Example: cy.checkLink('/some-path') — verifies a link doesn't 404
Cypress.Commands.add("checkLink", (href) => {
  cy.request({ url: href, failOnStatusCode: false }).its("status").should("be.lt", 400);
});
