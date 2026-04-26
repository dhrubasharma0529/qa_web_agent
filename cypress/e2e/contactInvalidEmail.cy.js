const contactPage = require('../support/pages/contactPage');

describe('Contact Form', () => {
  it('Submit contact form with invalid email format', () => {
    contactPage.visit();
    contactPage.getEmailInput().type('invalid-email');
    contactPage.getSendMessageBtn().click();
    cy.get('[class*="error"]').should('exist');
  });
});