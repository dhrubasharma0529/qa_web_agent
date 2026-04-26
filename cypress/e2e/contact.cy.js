const contactPage = require('../support/pages/contactPage');

describe('Contact Page', () => {
  it('User navigates to the Contact page and submits the contact form', () => {
    contactPage.visit();
    contactPage.getNameInput().type('John Doe');
    contactPage.getEmailInput().type('john.doe@example.com');
    contactPage.getMessageTextarea().type('Hello!');
    contactPage.getSendMessageBtn().click();
    cy.get('form').should('not.exist');
  });
});