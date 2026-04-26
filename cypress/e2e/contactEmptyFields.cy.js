const contactPage = require('../support/pages/contactPage');

describe('Contact Form', () => {
  it('Submit contact form with empty fields', () => {
    contactPage.visit();
    contactPage.getSendMessageBtn().click();
    cy.get('[class*="error"]').should('exist');
  });
});